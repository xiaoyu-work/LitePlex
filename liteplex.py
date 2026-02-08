#!/usr/bin/env python3
"""
LangGraph + vLLM: Perplexity-style assistant
Using proper LangChain tool calling pattern
"""

import json
import http.client
import requests
import time
import threading
import os
from typing import TypedDict, Sequence, Literal, List, Union, Dict
from typing_extensions import Annotated
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global LLM configuration (can be updated dynamically)
CURRENT_LLM_CONFIG = None

# Global search configuration
SEARCH_CONFIG = {
    'num_queries': 5,  # Default number of parallel queries (1-6)
    'memory_enabled': True  # Whether to use conversation history (5 Q&A pairs)
}

# Configuration
SERPER_API_KEY = os.getenv("SERPER_API_KEY")

# Default LLM Provider Configuration from environment
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "vllm").lower()
VLLM_URL = os.getenv("VLLM_URL", "http://localhost:1234/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "./Jan-v1-4B")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

# Validate required environment variables
if not SERPER_API_KEY:
    raise ValueError("SERPER_API_KEY not found in environment variables. Please set it in .env file.")

def set_llm_config(config):
    """Update the global LLM configuration from frontend"""
    global CURRENT_LLM_CONFIG
    CURRENT_LLM_CONFIG = config
    logger.info(f"LLM config updated: provider={config.get('provider', 'unknown')}")

def set_search_config(config):
    """Update the global search configuration from frontend"""
    global SEARCH_CONFIG
    # Frontend dropdown ensures 1-6, so just use the value directly
    SEARCH_CONFIG['num_queries'] = config.get('numQueries', 5)
    SEARCH_CONFIG['memory_enabled'] = config.get('memoryEnabled', True)
    
    logger.info(f"Search config updated: queries={SEARCH_CONFIG['num_queries']}, "
                f"memory={SEARCH_CONFIG['memory_enabled']}")

def get_llm_provider_config():
    """Get the current LLM provider configuration"""
    global CURRENT_LLM_CONFIG
    
    # Use frontend config if available
    if CURRENT_LLM_CONFIG:
        provider = CURRENT_LLM_CONFIG.get('provider', 'vllm')
        
        return {
            'provider': provider,
            'api_key': CURRENT_LLM_CONFIG.get('apiKey'),
            'model_name': CURRENT_LLM_CONFIG.get('modelName', MODEL_NAME),
            'vllm_url': CURRENT_LLM_CONFIG.get('vllmUrl', VLLM_URL)
        }
    
    # Fall back to environment variables
    return {
        'provider': LLM_PROVIDER,
        'api_key': None,
        'model_name': MODEL_NAME,
        'vllm_url': VLLM_URL
    }


# Helper function to extract domain from URL
def extract_domain(url: str) -> str:
    """Extract domain from URL for deduplication"""
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower()
    except (ValueError, AttributeError):
        return url.lower()

# Helper function to search single query
def search_single_query(query: str, num_results: int = 10) -> Dict:
    """Execute a single search query"""
    try:
        conn = http.client.HTTPSConnection("google.serper.dev")
        payload = json.dumps({"q": query, "num": num_results})
        headers = {
            'X-API-KEY': SERPER_API_KEY,
            'Content-Type': 'application/json'
        }
        conn.request("POST", "/search", payload, headers)
        res = conn.getresponse()
        data = res.read()
        result = json.loads(data.decode("utf-8"))
        conn.close()
        
        return {
            'query': query,
            'results': result.get('organic', []),
            'answerBox': result.get('answerBox', None)
        }
    except Exception as e:
        logger.error(f"Error searching '{query}': {e}")
        return {'query': query, 'results': [], 'answerBox': None}

# Helper function to deduplicate results by domain
def deduplicate_by_domain(all_results: List[Dict]) -> List[Dict]:
    """Deduplicate results keeping only the first/best result per domain"""
    seen_domains = set()
    deduplicated = []
    
    for result in all_results:
        domain = extract_domain(result.get('link', ''))
        if domain and domain not in seen_domains:
            seen_domains.add(domain)
            deduplicated.append(result)
    
    return deduplicated

# Import for tool schema
from pydantic import BaseModel, Field, field_validator

class GoogleSearchInput(BaseModel):
    """Input schema for google_search tool"""
    queries: List[str] = Field(
        description="List of search queries for comprehensive coverage"
    )
    
    @field_validator('queries')
    @classmethod
    def validate_queries_count(cls, v: List[str]) -> List[str]:
        # Adjust to configured number of queries
        target_count = SEARCH_CONFIG.get('num_queries', 5)
        if len(v) < target_count:
            # Pad with variations of existing queries
            while len(v) < target_count:
                v.append(v[0] if v else "")
        elif len(v) > target_count:
            v = v[:target_count]
        return v

# Main search tool - now accepts multiple queries
@tool(args_schema=GoogleSearchInput)
def google_search(queries: List[str]) -> str:
    """
    Search Google with multiple queries for comprehensive results.
    Number of queries is configurable (1-6) for optimal balance of speed and coverage.
    
    Args:
        queries: List of search queries (will be adjusted to configured count)
    """
    start_time = time.time()
    
    # Validate input
    if not isinstance(queries, list):
        queries = [queries] if isinstance(queries, str) else []
    
    # Adjust to configured number of queries
    target_count = SEARCH_CONFIG.get('num_queries', 5)
    if len(queries) < target_count:
        logger.info(f"📝 Expanding to {target_count} queries (received {len(queries)})")
        while len(queries) < target_count:
            queries.append(queries[0] if queries else "")
    elif len(queries) > target_count:
        logger.info(f"📝 Limiting to {target_count} queries (received {len(queries)})")
        queries = queries[:target_count]
    
    logger.info(f"🔍 [MULTI-SEARCH START] Executing {len(queries)} queries in parallel")
    for i, q in enumerate(queries, 1):
        logger.info(f"  Query {i}: {q}")
    
    try:
        # Parallel execution for maximum speed
        all_results = []
        all_answer_boxes = []
        
        with ThreadPoolExecutor(max_workers=6) as executor:
            # Submit all queries at once
            future_to_query = {
                executor.submit(search_single_query, query, 10): query 
                for query in queries
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_query):
                query = future_to_query[future]
                try:
                    result = future.result(timeout=3)  # 3 second timeout per query
                    all_results.extend(result['results'])
                    if result['answerBox']:
                        all_answer_boxes.append(result['answerBox'])
                    logger.info(f"✅ Query completed: '{query}' - {len(result['results'])} results")
                except Exception as e:
                    logger.error(f"❌ Query failed: '{query}' - {e}")
        
        parallel_time = time.time() - start_time
        logger.info(f"⏱️  [PARALLEL SEARCH] All queries completed in: {parallel_time:.2f}s")
        
        # Deduplicate by domain
        dedup_start = time.time()
        unique_results = deduplicate_by_domain(all_results)
        dedup_time = time.time() - dedup_start
        logger.info(f"⏱️  [DEDUPLICATION] {len(all_results)} → {len(unique_results)} results in {dedup_time:.2f}s")
        
        # Format results
        format_start = time.time()
        formatted = f"Search results for {len(queries)} queries:\n\n"
        
        # Add answer boxes if available
        if all_answer_boxes:
            formatted += "Quick Answers:\n"
            for i, answer in enumerate(all_answer_boxes[:3], 1):  # Limit to 3 answer boxes
                if isinstance(answer, dict):
                    formatted += f"{i}. {answer.get('answer', answer.get('snippet', ''))}\n"
            formatted += "\n"
        
        # Format unique results
        sources_data = []
        formatted += "Search Results:\n"
        
        for i, item in enumerate(unique_results[:40], 1):  # Limit to 40 unique results
            title = item.get('title', '')
            snippet = item.get('snippet', '')
            link = item.get('link', '')
            
            formatted += f"\n[{i}] {title}\n"
            formatted += f"    {snippet}\n"
            formatted += f"    URL: {link}\n"
            
            sources_data.append({
                'index': i,
                'title': title,
                'url': link
            })
        
        format_time = time.time() - format_start
        logger.info(f"⏱️  [FORMAT] Formatting took: {format_time:.2f}s")
        
        total_time = time.time() - start_time
        logger.info(f"🎯 [SEARCH COMPLETE] Total time: {total_time:.2f}s | Unique results: {len(unique_results)}")
        
        return json.dumps({
            'text': formatted,
            'sources': sources_data
        })
        
    except Exception as e:
        total_time = time.time() - start_time
        logger.error(f"❌ [SEARCH ERROR] Failed after {total_time:.2f}s: {e}")
        return json.dumps({'text': f"Search failed: {str(e)}", 'sources': []})


# Define the graph state
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_question: str  # Store the original user question for summarization


# Initialize LLM with tools properly bound
def create_llm_with_tools():
    """Create LLM with tools properly bound using LangChain pattern"""
    
    # Get current configuration
    config = get_llm_provider_config()
    provider = config['provider']
    model_name = config['model_name']
    
    logger.info(f"🔧 Creating LLM with provider: {provider}")
    logger.info(f"📝 Model: {model_name}")
    logger.info(f"🔑 API Key configured: {'Yes' if config.get('api_key') else 'No'}")
    if provider == "vllm":
        logger.info(f"🌐 vLLM URL: {config.get('vllm_url')}")
    
    # Create LLM instance based on provider
    if provider == "vllm":
        llm = ChatOpenAI(
            base_url=config['vllm_url'],
            model=model_name,
            api_key="not-needed",  # vLLM doesn't need API key
            temperature=0.7,
            max_tokens=16384,  # Use larger context window
            streaming=True  # Enable streaming for token-by-token output
        )
    elif provider == "openai":
        llm = ChatOpenAI(
            api_key=config['api_key'] or OPENAI_API_KEY,
            model=model_name,
            temperature=0.7,
            max_tokens=4096,
            streaming=True
        )
    elif provider == "anthropic":
        llm = ChatAnthropic(
            api_key=config['api_key'] or ANTHROPIC_API_KEY,
            model=model_name,
            temperature=0.7,
            max_tokens=4096,
            streaming=True
        )
    elif provider == "google":
        api_key = config['api_key'] or GOOGLE_API_KEY
        if not api_key:
            logger.error("❌ Google API key not configured!")
            raise ValueError("Google API key not configured. Please set it in the settings.")
        logger.info(f"🌟 Using Google Gemini")
        logger.info(f"  - Model: {model_name}")
        logger.info(f"  - API Key length: {len(api_key)} chars")
        logger.info(f"  - API Key prefix: {api_key[:10]}..." if api_key else "No key")
        try:
            llm = ChatGoogleGenerativeAI(
                google_api_key=api_key,
                model=model_name,
                temperature=0.7,
                streaming=True
            )
            logger.info("✅ Google Gemini LLM initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Google Gemini: {e}")
            raise
    elif provider == "deepseek":
        llm = ChatOpenAI(
            base_url="https://api.deepseek.com/v1",
            api_key=config['api_key'] or DEEPSEEK_API_KEY,
            model=model_name,
            temperature=0.7,
            max_tokens=4096,
            streaming=True
        )
    elif provider == "qwen":
        llm = ChatOpenAI(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key=config['api_key'] or DASHSCOPE_API_KEY,
            model=model_name,
            temperature=0.7,
            max_tokens=4096,
            streaming=True
        )
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")
    
    # Bind tools to LLM (this is the proper LangChain way)
    tools = [google_search]
    llm_with_tools = llm.bind_tools(tools)
    
    return llm_with_tools, tools


# Agent node - calls LLM with tools
def agent_node(state: AgentState) -> dict:
    """
    Agent node: LLM with tools bound decides what to do
    """
    node_start = time.time()
    logger.info("🤖 [AGENT NODE START]")
    
    messages = state["messages"]
    
    # Extract user question from the last human message
    user_question = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            user_question = msg.content
            break
    
    # Get LLM with tools
    setup_start = time.time()
    llm_with_tools, _ = create_llm_with_tools()
    setup_time = time.time() - setup_start
    logger.info(f"⏱️  [AGENT SETUP] LLM setup took: {setup_time:.2f}s")
    
    # Simple system message - just decide whether to use tools
    system_message = SystemMessage(content="""You are a helpful assistant with access to web search.

DECISION FLOW:
1. For stock ticker queries → Respond directly with stock chart widget (no tools)
2. For greetings, simple chat, or meta questions → Respond directly with JSON (no tools)
3. For factual questions or information requests → Use google_search tool
4. When unsure → Use google_search tool

STOCK QUERIES:
For ANY mention of stocks/companies (Tesla, TSLA, Apple, etc.):
- ALWAYS use google_search to get current info
- Include "stock price" and "stock news" in searches
- The summarizer will add [STOCK_CHART:TICKER] automatically

Example: "show me tsla and tell me recent news"
→ google_search(["TSLA stock price", "Tesla stock news today", "TSLA recent announcements", "Tesla latest developments", "TSLA stock analysis"])

OUTPUT FORMAT (when NOT using tools):
{
  "answer": "Your response in markdown format or [STOCK_CHART:SYMBOL] for stocks",
  "sources": []
}

WHEN TO USE TOOLS:
Use google_search for:
   - How-to questions (how to make, how to do, how to...)
   - Recipe or cooking questions
   - Factual questions, current events, or real-world information (except direct stock ticker queries)
   - Questions needing specific data or up-to-date information
   - General stock market questions (not specific tickers)

WHEN NOT TO USE TOOLS (respond directly with JSON):
   - Specific stock ticker queries (AAPL, TSLA, etc.)
   - Greetings (hi, hello, hey, good morning, etc.)
   - Thank you messages
   - Simple acknowledgments
   - Clarification requests about the conversation
   - Meta questions about yourself or this system

IMPORTANT:
The google_search tool requires a LIST of queries, not a single string!

MULTI-QUERY SEARCH REQUIREMENTS:
Provide queries as a list to google_search tool (system will adjust to configured count).
Generate diverse queries that cover different aspects of the user's question.

QUERY GENERATION STRATEGY:
- Query 1: User's exact question
- Query 2-3: Add context, related terms, or specific aspects
- Query 4-5: Alternative phrasings or different angles
- Query 6: Focus on authoritative sources or specific details

EXAMPLES:
User: "Trump Putin meeting"
Call: google_search(["Trump Putin meeting", "Trump Putin summit Alaska", "Trump Putin meeting outcomes", "Trump Putin Ukraine negotiations", "Trump Putin latest talks"])

User: "how to make milk tea"
Call: google_search(["how to make milk tea", "milk tea recipe ingredients", "bubble tea preparation steps", "homemade milk tea tutorial", "traditional milk tea method"])

User: "AAPL stock and why is it dropping?"
Call: google_search(["AAPL stock price today", "Apple stock dropping reasons", "AAPL news today", "Apple stock analysis", "Why is Apple stock down"])

User: "TSLA and recent news"
Call: google_search(["TSLA stock price", "Tesla stock news today", "Tesla latest announcements", "TSLA stock analysis", "Tesla Elon Musk news"])

IMPORTANT:
- DO NOT add years/dates unless user mentions them
- Each query should be distinct but related
- Always pass queries as a list: google_search([...])""")
    
    # Combine system message with conversation
    full_messages = [system_message] + list(messages)
    
    logger.info("🤖 [AGENT DECISION] LLM is deciding whether to use tools...")
    
    # Invoke LLM with tools - it will decide whether to use them
    llm_start = time.time()
    response = llm_with_tools.invoke(full_messages)
    llm_time = time.time() - llm_start
    logger.info(f"⏱️  [AGENT LLM] LLM decision took: {llm_time:.2f}s")
    
    # Log what LLM decided
    if response.tool_calls:
        logger.info(f"🔧 [AGENT TOOLS] LLM decided to use tools: {[tc['name'] for tc in response.tool_calls]}")
    else:
        logger.info("💬 [AGENT DIRECT] LLM responded directly without tools")
    
    total_time = time.time() - node_start
    logger.info(f"✅ [AGENT NODE COMPLETE] Total time: {total_time:.2f}s")
    
    return {"messages": [response], "user_question": user_question}


# Summarize node - takes tool results and summarizes them
def summarize_node(state: AgentState) -> dict:
    """
    Summarize node: Takes search results and user's question to create a focused answer
    """
    node_start = time.time()
    logger.info("📝 [SUMMARIZE NODE START]")
    
    messages = state["messages"]
    user_question = state.get("user_question", "")
    
    # Get the last tool result message (search results)
    parse_start = time.time()
    tool_result = None
    sources_data = []
    for msg in reversed(messages):
        if hasattr(msg, 'content') and msg.content:
            try:
                # Try to parse as JSON (new format)
                data = json.loads(msg.content)
                if 'text' in data and 'Search results for' in data['text']:
                    tool_result = data['text']
                    sources_data = data.get('sources', [])
                    break
            except (json.JSONDecodeError, ValueError, TypeError):
                # Fallback to old format
                if 'Search results for' in str(msg.content):
                    tool_result = msg.content
                    break

    parse_time = time.time() - parse_start
    logger.info(f"⏱️  [SUMMARIZE PARSE] Message parsing took: {parse_time:.2f}s")
    
    if not tool_result:
        # If no tool results, just pass through
        logger.info("⚠️  [SUMMARIZE SKIP] No tool results to summarize")
        return {"messages": []}
    
    # Get conversation history (last 5 exchanges)
    conversation_history = []
    for msg in messages[-10:]:  # Last 10 messages (5 exchanges)
        if isinstance(msg, HumanMessage):
            conversation_history.append(f"User: {msg.content}")
        elif isinstance(msg, AIMessage) and not hasattr(msg, 'tool_calls'):
            # Only include AI responses, not tool calls
            conversation_history.append(f"Assistant: {msg.content[:200]}...")  # Truncate long responses
    
    # Get current configuration for summarization
    config = get_llm_provider_config()
    provider = config['provider']
    model_name = config['model_name']
    
    # Create a simple LLM without tools for streaming based on provider
    if provider == "vllm":
        llm = ChatOpenAI(
            base_url=config['vllm_url'],
            model=model_name,
            api_key="not-needed",
            temperature=0.3,  # Lower temperature for accurate, fact-based summaries
            max_tokens=28000,  # Use most of the 32k context for output
            streaming=True  # Enable streaming for token-by-token output
        )
    elif provider == "openai":
        llm = ChatOpenAI(
            api_key=config['api_key'] or OPENAI_API_KEY,
            model=model_name,
            temperature=0.3,
            max_tokens=4096,
            streaming=True
        )
    elif provider == "anthropic":
        llm = ChatAnthropic(
            api_key=config['api_key'] or ANTHROPIC_API_KEY,
            model=model_name,
            temperature=0.3,
            max_tokens=4096,
            streaming=True
        )
    elif provider == "google":
        llm = ChatGoogleGenerativeAI(
            google_api_key=config['api_key'] or GOOGLE_API_KEY,
            model=model_name,
            temperature=0.1,  # Lower temperature for faster generation
            top_p=0.8,  # Reduce diversity for speed
            streaming=True
        )
    elif provider == "deepseek":
        llm = ChatOpenAI(
            base_url="https://api.deepseek.com/v1",
            api_key=config['api_key'] or DEEPSEEK_API_KEY,
            model=model_name,
            temperature=0.3,
            max_tokens=4096,
            streaming=True
        )
    elif provider == "qwen":
        llm = ChatOpenAI(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key=config['api_key'] or DASHSCOPE_API_KEY,
            model=model_name,
            temperature=0.3,
            max_tokens=4096,
            streaming=True
        )
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")
    
    # Create a focused prompt that answers the user's specific question
    summarize_prompt = SystemMessage(content="""You are a helpful assistant providing comprehensive, detailed answers like Perplexity.

MANDATORY RULE FOR STOCK QUERIES:
If the user asks about ANY company/stock (Tesla, TSLA, Apple, etc.) AND you see stock prices/tickers in search results:
→ Line 1 of your "answer" field MUST be: [STOCK_CHART:TICKER]
→ Line 2: Empty line (\\n\\n)
→ Line 3+: Your markdown content

CORRECT EXAMPLE for "show me tsla and tell me recent news":
{
  "answer": "[STOCK_CHART:TSLA]\\n\\n## Tesla Stock Overview\\n\\nTesla is currently trading at...",
  "sources": [{"index": 1, "title": "...", "url": "..."}]
}

WRONG EXAMPLE (missing stock chart):
{
  "answer": "## Tesla Stock Overview\\n\\nTesla is currently trading at...",
  "sources": [...]
}

OUTPUT FORMAT:
You MUST ALWAYS respond with a valid JSON object in this exact format:
{
  "answer": "Your complete markdown-formatted answer with citations using <sup>1,2,3</sup> tags",
  "sources": [
    {"index": 1, "title": "Source Title", "url": "https://example.com"},
    {"index": 2, "title": "Another Source", "url": "https://example2.com"}
  ]
}

Note: If you don't have sources (e.g., for greetings or direct answers), use empty array: "sources": []

IMPORTANT:
- The "answer" field should contain your full response in Markdown format
- Use sequential citation numbers starting from 1 (e.g., <sup>1</sup>, <sup>2</sup>, <sup>3</sup>)
- The "sources" array must be renumbered sequentially starting from 1
- Sources should be listed in the order they are first cited in your answer
- Each source must have index, title, and url
- DO NOT include the sources list in the answer field
- DO NOT skip numbers - if you cite sources from search results #1, #14, #19, renumber them as 1, 2, 3


ANSWER STYLE:
- Provide COMPREHENSIVE answers like Perplexity - extract and organize EVERY relevant detail
- Use PROPER MARKDOWN formatting:
  * Use ## for section headers
  * Use numbered lists: 1. 2. 3. for steps
  * Use bullet points: - or * for unordered lists
  * Add blank lines between sections for proper spacing
- Structure your answer based on the question type:

FOR EVENTS/NEWS (meetings, incidents, announcements):
  ## Background
  • Context and setup
  
  ## Key Developments
  • Timeline of events
  • Important moments
  
  ## Outcomes & Impact
  • Results and consequences
  • Different perspectives
  
  ## Future Implications
  • What's next

FOR HOW-TO/TUTORIALS (recipes, guides, instructions):
  Use this exact structure with proper markdown:
  
  ## Overview
  [Brief description paragraph]
  
  ## Requirements  
  - First requirement
  - Second requirement
  - Third requirement
  
  ## Step-by-Step Instructions
  1. First step with citation <sup>1</sup>
  2. Second step with citation <sup>2</sup>  
  3. Third step with citation <sup>3</sup>
  4. Continue numbering...
  
  ## Tips & Variations
  - First tip
  - Second tip
  - Alternative approaches
  
  ## Common Mistakes to Avoid
  - First mistake to avoid
  - Second mistake to avoid

FOR TECHNICAL/ERROR QUESTIONS:
  ## Problem Description
  What the error/issue is
  
  ## Root Cause
  Why this happens
  
  ## Solutions
  ### Method 1: [Name]
  • Steps to resolve
  • Code example if needed
  
  ### Method 2: [Name]
  • Alternative approach
  
  ## Best Practices
  • How to prevent this

FOR GENERAL INFORMATION:
  ## Overview
  Definition and introduction
  
  ## Key Information
  • Important facts
  • Core details
  
  ## Categories/Types
  • Different variations
  • Classifications
  
  ## Examples
  • Real-world applications
  • Use cases

ALWAYS:
- Include ALL specific details: dates, names, numbers, quotes, locations
- Use multiple paragraphs with smooth transitions  
- Aim for 300-600 words for completeness
- Present conflicting information if it exists
- End with a summary or key takeaways when appropriate

CRITICAL CITATION RULES:
⚠️ CITATIONS ARE MANDATORY - Every factual claim MUST have a citation
⚠️ Place citations IMMEDIATELY after the sentence containing the information
⚠️ NEVER group citations at the end of paragraphs
⚠️ Each distinct fact needs its own citation
⚠️ DO NOT include source URLs or links in the main answer text - only use <sup> numbers

FORMATTING RULES:
⚠️ Output valid GitHub-Flavored Markdown in the "answer" field
⚠️ Use ## for main headers, ### for subheaders
⚠️ Use - for bullet points (NOT • or *)
⚠️ Use 1. 2. 3. for numbered lists with proper spacing
⚠️ Add blank lines between sections (use \\n\\n in JSON)
⚠️ Format lists properly:
   - For bullet points: "- Item one\\n- Item two\\n- Item three"  
   - For numbered: "1. Step one\\n2. Step two\\n3. Step three"
⚠️ DO NOT use <br> tags - use \\n for line breaks in JSON

FORBIDDEN PHRASES (NEVER USE):
- "According to my search..."
- "Based on the information I found..."
- "The search results show..."
- "From what I gathered..."
Just state the facts directly with citations.

DECISION PROCESS:
1. Check if search results are relevant to the user's question
2. If relevant: Use them comprehensively with citations
3. If not relevant: Answer from knowledge without citations

IMPORTANT:
- Be comprehensive but stay focused on the question
- Use formatting (bullet points, sections) to improve readability
- Include practical examples and step-by-step solutions when applicable

CITATION RENUMBERING RULES:
When citing search results, you MUST renumber them sequentially:
- If you cite search results #8, #1, #4, #16, #17, #18, #25, #24, #2, #12, #11
- Renumber them as 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11 in your answer
- In the JSON "sources" array, list them with these new sequential numbers

EXAMPLE:
Search result #8 becomes citation <sup>1</sup> and source index 1
Search result #16 becomes citation <sup>2</sup> and source index 2
And so on...

The key is: Citations must be numbered 1, 2, 3, 4... regardless of original search result numbers

WHEN ANSWERING DIRECTLY (search results not relevant or simple greeting):
- Still use JSON format: {"answer": "Your response", "sources": []}
- Write your answer WITHOUT citations
- Keep sources array empty

VERY IMPORTANT:
- ALWAYS output valid JSON format
- If you have citations, include sources in the array
- If no citations, sources array must be empty []
- Always renumber citations sequentially starting from 1
- The numbers in your <sup> tags should be 1,2,3,4... based on order of use
""")
    
    # Build the context with conversation history
    context = ""
    if conversation_history:
        context += "Recent conversation:\n" + "\n".join(conversation_history[-4:]) + "\n\n"  # Last 2 exchanges
    
    context += f"User's current question: {user_question}\n\n"
    context += f"Information to use for answering:\n{tool_result}\n\n"
    
    # Add sources information for proper citation
    if sources_data:
        context += "Format these sources in your response:\n"
        for source in sources_data:
            context += f"{source['index']}. [{source['title']}]({source['url']})\n"
    
    # Ask to answer the specific question with strong emphasis on stock chart detection
    summary_request = HumanMessage(content=f"""INSTRUCTION: If the search results contain stock prices or the user asks about a company/stock, 
you MUST start your answer with [STOCK_CHART:TICKER] where TICKER is extracted from the search results.

Question: {user_question}

Search results show stock tickers? If yes, your answer MUST start with [STOCK_CHART:TICKER]

Context:
{context}""")
    
    logger.info("📝 [SUMMARIZE GENERATE] Generating focused answer...")
    
    # Get answer with timeout handling
    llm_start = time.time()
    try:
        summary = llm.invoke([summarize_prompt, summary_request])
        llm_time = time.time() - llm_start
        logger.info(f"⏱️  [SUMMARIZE LLM] LLM summarization took: {llm_time:.2f}s")
    except Exception as e:
        logger.error(f"❌ [SUMMARIZE ERROR] LLM invocation failed: {e}")
        # Fallback to a simple response
        fallback_content = json.dumps({
            "answer": "I'm having trouble generating a response. Please try again or check your LLM configuration.",
            "sources": []
        })
        summary = AIMessage(content=fallback_content)
        llm_time = time.time() - llm_start
        logger.info(f"⏱️  [SUMMARIZE FALLBACK] Used fallback after: {llm_time:.2f}s")
    
    total_time = time.time() - node_start
    logger.info(f"✅ [SUMMARIZE NODE COMPLETE] Total time: {total_time:.2f}s")
    
    return {"messages": [summary]}


# Router to decide next step after agent
def should_continue(state: AgentState) -> Literal["tools", "end"]:
    """
    Determine whether to continue to tools or end
    """
    messages = state["messages"]
    last_message = messages[-1]
    
    # Check if the last message has tool calls
    if last_message.tool_calls:
        logger.info("➡️ Routing to tools node")
        return "tools"
    else:
        logger.info("➡️ Routing to end")
        return "end"


# Router after tools - go to end to allow streaming summarization
def after_tools(state: AgentState) -> Literal["end", "agent"]:
    """
    After tools, route to end so we can do streaming summarization outside the graph
    """
    messages = state["messages"]

    # Check if we have search results in the recent messages
    for msg in reversed(messages[-3:]):  # Check last 3 messages
        if hasattr(msg, 'content') and 'Search results for' in str(msg.content):
            logger.info("➡️ Routing to END (will do streaming summarization)")
            return "end"

    # Otherwise go back to agent
    logger.info("➡️ Routing back to agent")
    return "agent"


# Streaming summarization generator (for real streaming)
def stream_summarize(messages, user_question, stop_event=None):
    """
    Generator that streams summarization tokens.
    Yields: (token_type, content) tuples
    - ("token", "text") for streaming tokens
    - ("sources", [...]) for sources at the end
    - ("done", full_content) when complete
    """
    logger.info("📝 [STREAM SUMMARIZE START]")

    # Extract search results from messages
    tool_result = None
    sources_data = []
    for msg in reversed(messages):
        if hasattr(msg, 'content') and msg.content:
            try:
                data = json.loads(msg.content)
                if 'text' in data and 'Search results for' in data['text']:
                    tool_result = data['text']
                    sources_data = data.get('sources', [])
                    break
            except (json.JSONDecodeError, ValueError, TypeError):
                if 'Search results for' in str(msg.content):
                    tool_result = msg.content
                    break

    if not tool_result:
        logger.info("⚠️ [STREAM SUMMARIZE] No tool results to summarize")
        yield ("done", "")
        return

    # Get LLM config
    config = get_llm_provider_config()
    provider = config['provider']
    model_name = config['model_name']

    # Create LLM based on provider
    if provider == "vllm":
        llm = ChatOpenAI(
            base_url=config['vllm_url'],
            model=model_name,
            api_key="not-needed",
            temperature=0.3,
            max_tokens=28000,
            streaming=True
        )
    elif provider == "openai":
        llm = ChatOpenAI(
            api_key=config['api_key'] or OPENAI_API_KEY,
            model=model_name,
            temperature=0.3,
            max_tokens=4096,
            streaming=True
        )
    elif provider == "anthropic":
        llm = ChatAnthropic(
            api_key=config['api_key'] or ANTHROPIC_API_KEY,
            model=model_name,
            temperature=0.3,
            max_tokens=4096,
            streaming=True
        )
    elif provider == "google":
        llm = ChatGoogleGenerativeAI(
            google_api_key=config['api_key'] or GOOGLE_API_KEY,
            model=model_name,
            temperature=0.1,
            top_p=0.8,
            streaming=True
        )
    elif provider == "deepseek":
        llm = ChatOpenAI(
            base_url="https://api.deepseek.com/v1",
            api_key=config['api_key'] or DEEPSEEK_API_KEY,
            model=model_name,
            temperature=0.3,
            max_tokens=4096,
            streaming=True
        )
    elif provider == "qwen":
        llm = ChatOpenAI(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key=config['api_key'] or DASHSCOPE_API_KEY,
            model=model_name,
            temperature=0.3,
            max_tokens=4096,
            streaming=True
        )
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")

    # Streaming prompt - outputs markdown directly (no JSON wrapper)
    system_prompt = SystemMessage(content="""You are a helpful assistant providing comprehensive, detailed answers like Perplexity.

OUTPUT FORMAT: Write your answer directly in Markdown format. DO NOT wrap in JSON.

STOCK QUERIES: If the user asks about a stock/company and you see stock data, start with:
[STOCK_CHART:TICKER]

Then write your markdown answer.

CITATION RULES:
- Use <sup>1</sup>, <sup>2</sup>, etc. to cite sources
- Number citations sequentially starting from 1
- Place citations immediately after the relevant information

ANSWER STYLE:
- Use ## for section headers
- Use bullet points and numbered lists
- Be comprehensive but focused
- Include specific details: dates, names, numbers

FORBIDDEN: Do not say "According to search results" or similar phrases. Just state the facts.""")

    # Build context
    context = f"User's question: {user_question}\n\nInformation to answer with:\n{tool_result}"

    if sources_data:
        context += "\n\nAvailable sources (cite by number):\n"
        for source in sources_data:
            context += f"{source['index']}. [{source['title']}]({source['url']})\n"

    user_msg = HumanMessage(content=context)

    logger.info("📝 [STREAM SUMMARIZE] Starting LLM stream...")

    # Stream the response
    full_content = ""
    try:
        for chunk in llm.stream([system_prompt, user_msg]):
            if stop_event and stop_event.is_set():
                logger.info("Request cancelled during streaming")
                return

            if hasattr(chunk, 'content') and chunk.content:
                full_content += chunk.content
                yield ("token", chunk.content)

        logger.info(f"📝 [STREAM SUMMARIZE] Complete, {len(full_content)} chars")

        # Send sources
        yield ("sources", sources_data)

        # Send completion
        yield ("done", full_content)

    except Exception as e:
        logger.error(f"❌ [STREAM SUMMARIZE ERROR] {e}")
        yield ("error", str(e))


# Create the graph
def create_perplexity_graph():
    """
    Create the LangGraph workflow with proper tool calling and summarization
    Workflow: user -> agent -> tools -> summarize -> end
    """
    # Initialize workflow
    workflow = StateGraph(AgentState)
    
    # Get tools for ToolNode
    _, tools = create_llm_with_tools()
    
    # Create ToolNode with our tools
    tool_node = ToolNode(tools)
    
    # Add nodes
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)  # Using ToolNode from LangGraph
    workflow.add_node("summarize", summarize_node)  # New summarize node
    
    # Set entry point
    workflow.set_entry_point("agent")
    
    # Add conditional routing from agent
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "end": END
        }
    )
    
    # After tools, route to end (for streaming summarization) or back to agent
    workflow.add_conditional_edges(
        "tools",
        after_tools,
        {
            "end": END,
            "agent": "agent"
        }
    )
    
    # Compile the graph
    app = workflow.compile()
    
    logger.info("📊 Graph compiled with workflow: agent -> tools -> summarize -> end")
    
    return app


# Main assistant class
class PerplexityAssistant:
    """
    Main assistant using LangGraph with proper tool calling
    """
    
    def __init__(self):
        self.graph = create_perplexity_graph()
        self.message_history = []  # Maintain full message history
        self.conversation_history = []  # Keep simplified history for reference
        logger.info("✅ Perplexity Assistant initialized with LangGraph")
    
    def chat(self, user_input: str) -> str:
        """
        Process user input through the graph with conversation history
        """
        # Add user message to history
        user_msg = HumanMessage(content=user_input)
        self.message_history.append(user_msg)
        
        # Create initial state with conversation history based on config
        if SEARCH_CONFIG.get('memory_enabled', True):
            # Keep last 5 questions (10 messages: 5 user + 5 assistant)
            messages_to_include = self.message_history[-10:]
        else:
            # No history, just current message
            messages_to_include = [user_msg]
        
        initial_state = {
            "messages": messages_to_include,
            "user_question": user_input  # Pass the current question
        }
        
        logger.info(f"\n{'='*60}")
        logger.info(f"👤 USER: {user_input}")
        logger.info(f"{'='*60}")
        
        # Run the graph
        result = self.graph.invoke(initial_state)
        
        # Get the final message
        final_message = result["messages"][-1]
        
        # Add assistant response to history
        self.message_history.append(final_message)
        
        # Track if tools were used
        used_tools = any(msg.tool_calls for msg in result["messages"] if hasattr(msg, 'tool_calls'))
        
        # Store in simplified history
        self.conversation_history.append({
            "user": user_input,
            "assistant": final_message.content,
            "used_tools": used_tools
        })
        
        # Format response
        response = final_message.content
        
        return response
    
    def stream_chat(self, user_input: str, stop_event=None):
        """
        Stream the chat response with cancellation support - with real streaming
        """
        overall_start = time.time()
        
        # Add user message to history
        user_msg = HumanMessage(content=user_input)
        self.message_history.append(user_msg)
        
        # Create initial state with conversation history based on config
        if SEARCH_CONFIG.get('memory_enabled', True):
            # Keep last 5 questions (10 messages: 5 user + 5 assistant)
            messages_to_include = self.message_history[-10:]
        else:
            # No history, just current message
            messages_to_include = [user_msg]
        
        initial_state = {
            "messages": messages_to_include,
            "user_question": user_input  # Pass the current question
        }
        
        logger.info(f"\n{'='*60}")
        logger.info(f"👤 USER: {user_input}")
        logger.info(f"⏱️  [STREAM START] Starting request processing")
        logger.info(f"{'='*60}")
        
        # Check if this looks like a question that needs search
        # Simple heuristic: questions about facts, current events, etc.
        needs_search = any(word in user_input.lower() for word in [
            'what', 'when', 'where', 'who', 'how', 'why', 'price', 'cost', 
            'latest', 'current', 'today', 'news', 'stock', '?'
        ])
        
        if needs_search:
            # Send searching status immediately
            yield "STATUS:SEARCHING"
            # Small delay to let the animation show
            time.sleep(0.5)
            
            # Check if cancelled
            if stop_event and stop_event.is_set():
                logger.info("Request cancelled during search")
                return
        
        # Use streaming directly from the graph
        try:
            full_content = ""
            used_tools = False
            all_messages = list(messages_to_include)  # Track all messages
            sources_data = []

            # Stream through the graph
            graph_start = time.time()
            logger.info(f"⏱️  [GRAPH START] Beginning graph execution")

            for event in self.graph.stream(initial_state):
                if stop_event and stop_event.is_set():
                    logger.info("Request cancelled during streaming")
                    return

                for node_name, node_data in event.items():
                    logger.info(f"🔄 [NODE] {node_name}")

                    if node_name == "tools":
                        used_tools = True
                        yield "STATUS:SUMMARIZING"
                        # Collect messages from tools
                        if "messages" in node_data:
                            all_messages.extend(node_data["messages"])

                    elif node_name == "agent":
                        if "messages" in node_data:
                            all_messages.extend(node_data["messages"])

            graph_time = time.time() - graph_start
            logger.info(f"⏱️  [GRAPH COMPLETE] Graph took: {graph_time:.2f}s")

            # If tools were used, do streaming summarization
            if used_tools:
                logger.info("📝 [STREAMING SUMMARIZE] Starting...")

                for result in stream_summarize(all_messages, user_input, stop_event):
                    if stop_event and stop_event.is_set():
                        return

                    result_type, content = result

                    if result_type == "token":
                        # Stream each token to frontend
                        yield f"STREAM:{content}"
                        full_content += content

                    elif result_type == "sources":
                        sources_data = content
                        # Send sources as JSON
                        yield f"SOURCES:{json.dumps(content)}"

                    elif result_type == "done":
                        logger.info(f"📝 [STREAMING SUMMARIZE] Done, {len(content)} chars")

                    elif result_type == "error":
                        logger.error(f"❌ [STREAMING SUMMARIZE] Error: {content}")
                        yield f"Error: {content}"

            # Store in history
            if full_content:
                final_msg = AIMessage(content=full_content)
                self.message_history.append(final_msg)
                self.conversation_history.append({
                    "user": user_input,
                    "assistant": full_content,
                    "used_tools": used_tools
                })

            total_time = time.time() - overall_start
            logger.info(f"⏱️  [REQUEST COMPLETE] Total: {total_time:.2f}s")
            logger.info(f"{'='*60}\n")
                
        except Exception as e:
            total_time = time.time() - overall_start
            logger.error(f"❌ [ERROR] Request failed after {total_time:.2f}s: {e}")
            yield f"Error: {str(e)}"
            return
    


# Interactive CLI
def main():
    """
    Interactive chat interface
    """
    print("""
╔═══════════════════════════════════════════════════════╗
║     LangChain + LangGraph + vLLM Assistant           ║
╚═══════════════════════════════════════════════════════╝

🔄 Workflow:
┌────────┐     ┌─────────────┐     ┌────────────┐     ┌──────────┐
│  User  │ --> │ Agent (LLM) │ --> │  ToolNode  │ --> │ Summarize│
└────────┘     └─────────────┘     └────────────┘     └──────────┘
                    ↓                (google_search)         ↓
               [Decides to use                           [Clean summary
                tools or not]                             without bias]

✨ LLM autonomously decides when to search
📚 Using proper LangChain tool calling pattern

Type 'exit' to quit
""")
    # Initialize assistant
    assistant = PerplexityAssistant()
    
    while True:
        try:
            # Get user input
            user_input = input("\n👤 You: ")
            
            if user_input.lower() == 'exit':
                print("👋 Goodbye!")
                break
            
            # Stream and display response
            print("\n🤖 Assistant: ", end="", flush=True)
            
            # Stream the response
            full_response = ""
            for chunk in assistant.stream_chat(user_input):
                print(chunk, end="", flush=True)
                full_response += chunk
            
            print()  # New line after response
            
            # Store in history
            assistant.conversation_history.append({
                "user": user_input,
                "assistant": full_response,
            })
            
        except KeyboardInterrupt:
            print("\n\nUse 'exit' to quit")
        except Exception as e:
            print(f"\n❌ Error: {e}")
            logger.error(f"Error in chat: {e}", exc_info=True)


if __name__ == "__main__":
    main()