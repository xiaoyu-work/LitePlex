#!/usr/bin/env python3
"""
Simple interactive chat client for vLLM with MCP tools
Clean streaming output without external dependencies
"""

import json
import requests
import sys

# Configuration
API_URL = "http://localhost:1234/v1/chat/completions"  # Single port with integrated MCP

class Colors:
    """ANSI color codes"""
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    DIM = '\033[2m'
    BOLD = '\033[1m'
    END = '\033[0m'


def stream_chat(messages):
    """Stream chat response with clean output"""
    data = {
        "messages": messages,
        "stream": True,
        "temperature": 0.7,
        "max_tokens": 2048
    }
    
    try:
        response = requests.post(
            API_URL,
            json=data,
            stream=True,
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        
        full_response = ""
        in_thinking = False
        tool_calling = False
        
        for line in response.iter_lines():
            if not line:
                continue
            
            line_str = line.decode('utf-8')
            
            # Skip empty and done markers
            if not line_str.strip() or line_str == "data: [DONE]":
                continue
            
            # Remove "data: " prefix
            if line_str.startswith("data: "):
                line_str = line_str[6:]
            
            try:
                chunk = json.loads(line_str)
                
                if "choices" in chunk and chunk["choices"]:
                    choice = chunk["choices"][0]
                    
                    if "delta" in choice:
                        delta = choice["delta"]
                        
                        # Handle tool calls
                        if "tool_calls" in delta:
                            tool_calling = True
                            for tool_call in delta["tool_calls"]:
                                if "function" in tool_call:
                                    func = tool_call["function"]
                                    if "name" in func:
                                        print(f"\n{Colors.CYAN}🔧 Calling: {func['name']}{Colors.END}")
                                    if "arguments" in func and func["arguments"]:
                                        try:
                                            args = json.loads(func["arguments"])
                                            print(f"{Colors.DIM}   Query: {args.get('query', '')}{Colors.END}")
                                        except:
                                            pass
                        
                        # Handle content
                        if "content" in delta and delta["content"]:
                            content = delta["content"]
                            full_response += content
                            
                            # Handle thinking tags
                            if "<think>" in content:
                                in_thinking = True
                                print(f"\n{Colors.DIM}💭 Thinking...{Colors.END}", end="")
                            elif "</think>" in content:
                                in_thinking = False
                                print()  # New line after thinking
                            elif in_thinking:
                                # Don't print thinking content
                                pass
                            elif not tool_calling:
                                # Print normal content
                                print(content, end="", flush=True)
                    
                    # Handle finish reason
                    if "finish_reason" in choice and choice["finish_reason"]:
                        if choice["finish_reason"] == "tool_calls":
                            print(f"\n{Colors.YELLOW}⏳ Getting search results...{Colors.END}")
                            tool_calling = False
                            
            except json.JSONDecodeError:
                continue
            except Exception as e:
                print(f"\n{Colors.RED}Error: {e}{Colors.END}")
        
        print()  # Final newline
        return full_response
        
    except requests.exceptions.RequestException as e:
        print(f"\n{Colors.RED}Connection error: {e}{Colors.END}")
        return None


def main():
    """Main chat loop"""
    # Check server
    try:
        requests.get(API_URL.replace("/v1/chat/completions", "/"), timeout=2)
        print(f"{Colors.GREEN}✓ Connected to vLLM server{Colors.END}")
    except:
        print(f"{Colors.RED}Error: Server not running. Start with: ./start.sh{Colors.END}")
        sys.exit(1)
    
    print(f"{Colors.CYAN}{Colors.BOLD}vLLM Chat with MCP Tools{Colors.END}")
    print("Commands: 'exit' to quit, 'clear' to reset\n")
    
    messages = []
    
    while True:
        try:
            # Get user input
            user_input = input(f"{Colors.GREEN}{Colors.BOLD}You:{Colors.END} ")
            
            if user_input.lower() == 'exit':
                print(f"{Colors.YELLOW}Goodbye!{Colors.END}")
                break
            elif user_input.lower() == 'clear':
                messages = []
                print(f"{Colors.YELLOW}Conversation cleared{Colors.END}")
                continue
            
            # Add user message
            messages.append({"role": "user", "content": user_input})
            
            # Get and stream response
            print(f"{Colors.BLUE}{Colors.BOLD}Assistant:{Colors.END} ", end="")
            response = stream_chat(messages)
            
            # Add to history
            if response:
                messages.append({"role": "assistant", "content": response})
            
            print()  # Extra line for readability
            
        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}Use 'exit' to quit{Colors.END}")
        except Exception as e:
            print(f"{Colors.RED}Error: {e}{Colors.END}")


if __name__ == "__main__":
    main()