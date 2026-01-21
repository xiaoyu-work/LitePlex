#!/usr/bin/env python3
"""
LitePlex API Backend Server
"""

from flask import Flask, request, Response, stream_with_context, jsonify
from flask_cors import CORS
import json
import time
import re
import threading
import uuid
import os
from liteplex import PerplexityAssistant, set_llm_config, set_search_config
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)
logger = logging.getLogger(__name__)

# Also ensure liteplex module logs are visible
liteplex_logger = logging.getLogger('liteplex')
liteplex_logger.setLevel(logging.INFO)

app = Flask(__name__)
CORS(app)

# Global assistant instance
assistant = None

# Track active requests by session ID
active_requests = {}
active_requests_lock = threading.Lock()

def init_assistant():
    """Initialize the assistant"""
    global assistant
    if not assistant:
        assistant = PerplexityAssistant()
        logger.info("✅ Assistant initialized for API server")

@app.route('/')
def index():
    """API root endpoint"""
    return jsonify({
        'name': 'LitePlex API',
        'version': '1.0.0',
        'status': 'running',
        'frontend': 'Please run the frontend on http://localhost:3000',
        'backend': f'Running on {os.getenv("BACKEND_HOST", "0.0.0.0")}:{os.getenv("BACKEND_PORT", "8088")}',
        'endpoints': {
            '/api/chat': 'POST - Send chat messages (with sessionId)',
            '/api/stop': 'POST - Stop generation for a session',
            '/api/health': 'GET - Health check'
        }
    })

@app.route('/api/chat', methods=['POST'])
def chat():
    """Handle chat requests with streaming"""
    try:
        data = request.json
        
        # Get messages from request
        messages = data.get('messages', [])
        if not messages:
            return jsonify({'error': 'No messages provided'}), 400
        
        # Get the last user message
        message = messages[-1].get('content', '')
        if not message:
            return jsonify({'error': 'No message content'}), 400
        
        # Get LLM configuration if provided
        llm_config = data.get('llmConfig')
        if llm_config:
            logger.info(f"📡 Received LLM config from frontend:")
            logger.info(f"  - Provider: {llm_config.get('provider', 'not set')}")
            logger.info(f"  - Model: {llm_config.get('modelName', 'not set')}")
            logger.info(f"  - API Key: {'✓ Provided' if llm_config.get('apiKey') else '✗ Missing'}")
            if llm_config.get('vllmUrl'):
                logger.info(f"  - vLLM URL: {llm_config.get('vllmUrl')}")
            # Pass the config to the assistant
            set_llm_config(llm_config)
        else:
            logger.warning("⚠️ No LLM config received from frontend, using defaults")
        
        # Get search configuration if provided
        search_config = data.get('searchConfig')
        if search_config:
            logger.info(f"🔍 Received search config from frontend:")
            logger.info(f"  - Num queries: {search_config.get('numQueries', 'not set')}")
            logger.info(f"  - Memory enabled: {search_config.get('memoryEnabled', 'not set')}")
            set_search_config(search_config)
        
        session_id = data.get('sessionId', str(uuid.uuid4()))  # Get or generate session ID
        
        # Create a stop event for this request
        stop_event = threading.Event()
        
        # Register this request with its session ID
        with active_requests_lock:
            active_requests[session_id] = stop_event
            logger.info(f"Starting request for session {session_id}")
        
        def generate():
            """Generator for streaming response"""
            # Stream the response
            full_response = ""
            sources_data = []

            try:
                for chunk in assistant.stream_chat(message, stop_event):
                    # Check for status signals
                    if chunk.startswith("STATUS:"):
                        status = chunk.replace("STATUS:", "").lower()
                        logger.info(f"Sending status: {status}")
                        yield f"data: {json.dumps({'type': 'status', 'status': status})}\n\n"
                        continue

                    # Check for thinking content
                    if chunk.startswith("THINKING:"):
                        thinking_content = chunk.replace("THINKING:", "")
                        try:
                            thinking_content = thinking_content.replace('\x00', '').encode('utf-8', 'ignore').decode('utf-8')
                            yield f"data: {json.dumps({'type': 'thinking', 'content': thinking_content})}\n\n"
                        except Exception as e:
                            logger.error(f"Error encoding thinking content: {e}")
                        continue

                    # Check for streaming content (real-time tokens)
                    if chunk.startswith("STREAM:"):
                        token = chunk[7:]  # Remove "STREAM:" prefix
                        full_response += token
                        # Send each token immediately for real-time streaming
                        yield f"data: {json.dumps({'type': 'content', 'content': token})}\n\n"
                        continue

                    # Check for sources
                    if chunk.startswith("SOURCES:"):
                        sources_json = chunk[8:]  # Remove "SOURCES:" prefix
                        try:
                            sources_data = json.loads(sources_json)
                            logger.info(f"Received {len(sources_data)} sources")
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse sources: {e}")
                        continue

                    # Legacy: handle raw content (non-prefixed)
                    if chunk and not chunk.startswith("Error:"):
                        full_response += chunk
                        yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"
                
                # Log completion
                logger.info(f"Total response: {len(full_response)} chars")

                # Send sources if we have them (already collected via SOURCES: protocol)
                if sources_data:
                    logger.info(f"Sending {len(sources_data)} sources")
                    yield f"data: {json.dumps({'type': 'sources', 'sources': sources_data})}\n\n"
                else:
                    logger.info("No sources to send")
                    yield f"data: {json.dumps({'type': 'sources', 'sources': []})}\n\n"

                # Send completion signal
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
            except GeneratorExit:
                # Client disconnected
                logger.info(f"Client disconnected for session {session_id} (GeneratorExit)")
                stop_event.set()
            except Exception as e:
                logger.error(f"Error during streaming for session {session_id}: {e}")
                stop_event.set()
            finally:
                # Clean up the request from active_requests
                with active_requests_lock:
                    if session_id in active_requests:
                        del active_requests[session_id]
                        logger.info(f"Cleaned up request for session {session_id}")
        
        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive'
            }
        )
    
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/stop', methods=['POST'])
def stop_generation():
    """Stop generation for a specific session"""
    try:
        data = request.json
        session_id = data.get('sessionId')
        
        if not session_id:
            return jsonify({'error': 'No sessionId provided'}), 400
        
        with active_requests_lock:
            if session_id in active_requests:
                stop_event = active_requests[session_id]
                stop_event.set()
                logger.info(f"Stop requested for session {session_id}")
                return jsonify({'status': 'stopped', 'sessionId': session_id})
            else:
                logger.warning(f"No active request found for session {session_id}")
                return jsonify({'status': 'no_active_request', 'sessionId': session_id})
    
    except Exception as e:
        logger.error(f"Stop error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config', methods=['POST'])
def update_config():
    """Update LLM configuration"""
    try:
        config = request.json
        logger.info(f"Updating LLM config: {config}")
        
        # Store the configuration
        set_llm_config(config)
        
        return jsonify({'status': 'success', 'message': 'Configuration updated'})
    except Exception as e:
        logger.error(f"Config update error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'assistant': assistant is not None})

@app.before_request
def ensure_assistant():
    """Ensure assistant is initialized"""
    init_assistant()

if __name__ == '__main__':
    import subprocess
    import sys
    
    # Get configuration from environment variables
    BACKEND_HOST = os.getenv('BACKEND_HOST', '0.0.0.0')
    BACKEND_PORT = int(os.getenv('BACKEND_PORT', '8088'))
    
    # Kill any existing process on the configured port
    try:
        # Find process using the port
        result = subprocess.run(['lsof', f'-ti:{BACKEND_PORT}'], capture_output=True, text=True)
        if result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                try:
                    subprocess.run(['kill', '-9', pid])
                    print(f"✅ Killed existing process on port {BACKEND_PORT} (PID: {pid})")
                except:
                    pass
            # Wait a moment for port to be released
            time.sleep(1)
    except Exception as e:
        # lsof might not be available on all systems
        pass
    
    print(f"""
╔═══════════════════════════════════════════════════════╗
║     LitePlex API Backend Server                      ║
╚═══════════════════════════════════════════════════════╝

Starting API server on http://{BACKEND_HOST}:{BACKEND_PORT}

📌 This is the API backend only!
🖥️  To use the web interface, run the frontend:
    cd frontend
    npm install
    npm run dev
    
Then open http://localhost:3000 in your browser

Press Ctrl+C to stop the server
""")
    
    # Initialize assistant
    init_assistant()
    
    # Run the app on configured host and port
    app.run(host=BACKEND_HOST, port=BACKEND_PORT, debug=False, threaded=True, use_reloader=False)