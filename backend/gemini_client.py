"""
Gemini REST API Client for Leo
==============================

Uses the PUBLISHER ENDPOINT:
https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent?key={API_KEY}

This gives access to:
- gemini-3-pro-preview ($2/1M input, $12/1M output) - Deep reasoning
- gemini-2.5-flash ($0.30/1M input, $2.50/1M output) - Fast multimodal
- gemini-2.5-flash-lite ($0.075/1M input, $0.30/1M output) - Cheapest
- gemini-exp-1206 - Experimental high-reasoning model

Reference: src/lib/gemini-rest-client.ts
"""

import os
import json
import time
import logging
from typing import Optional, Dict, List, Any, Callable
from dataclasses import dataclass

import requests
from dotenv import load_dotenv
from pathlib import Path

# Load environment from Leo directory (standalone)
leo_root = Path(__file__).parent.parent  # Leo/
load_dotenv(leo_root / ".env.local")
load_dotenv(Path(__file__).parent / ".env", override=True)

# Ensure Gemini key is available (fallback)
if not os.getenv("GEMINI_API_KEY_HELLO") and not os.getenv("GOOGLE_AI_API_KEY") and not os.getenv("GEMINI_API_KEY"):
    os.environ["GEMINI_API_KEY_HELLO"] = ""

logger = logging.getLogger(__name__)

# API Configuration
# Two endpoints available:
# 1. generativelanguage.googleapis.com/v1beta - Google AI Studio API (works with GOOGLE_AI_API_KEY)
# 2. aiplatform.googleapis.com/v1/publishers - Vertex AI publisher endpoint (works with GEMINI_API_KEY)
GENAI_ENDPOINT = "generativelanguage.googleapis.com"
VERTEX_ENDPOINT = "aiplatform.googleapis.com"
DEFAULT_MODEL = "gemini-3-flash-preview"

# Model pricing per 1M tokens (for cost tracking)
MODEL_PRICING = {
    "gemini-3-pro-preview": {"input": 2.00, "output": 12.00},
    "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-exp-1206": {"input": 0.00, "output": 0.00},  # Experimental - free?
}

# Default safety settings (OFF to allow all content)
DEFAULT_SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "OFF"},
]


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    
    @property
    def estimated_cost(self) -> float:
        """Estimate cost based on default model pricing."""
        pricing = MODEL_PRICING.get(DEFAULT_MODEL, MODEL_PRICING["gemini-2.5-flash"])
        input_cost = (self.prompt_tokens / 1_000_000) * pricing["input"]
        output_cost = (self.completion_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost


@dataclass
class GeminiResponse:
    success: bool
    text: Optional[str] = None
    error: Optional[str] = None
    usage: Optional[TokenUsage] = None
    model: Optional[str] = None
    raw_response: Optional[str] = None


class GeminiClient:
    """
    REST API client for Gemini.
    Supports both Google AI Studio (generativelanguage) and Vertex AI (aiplatform) endpoints.
    Supports function calling for Leo's tools.
    """
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        # Try keys in order of preference:
        # 1. GOOGLE_AI_API_KEY - puedo_casa project key (PREFERRED)
        # 2. GEMINI_API_KEY_HELLO - The "hello@" project key (fallback)
        # 3. GEMINI_API_KEY / GOOGLE_CLOUD_API_KEY - Vertex AI keys
        self.google_ai_key = os.getenv("GOOGLE_AI_API_KEY")  # puedo_casa - PRIORITY
        self.hello_key = os.getenv("GEMINI_API_KEY_HELLO")
        self.vertex_ai_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_CLOUD_API_KEY")
        
        # Use provided key or best available (puedo_casa first!)
        self.api_key = api_key or self.google_ai_key or self.hello_key or self.vertex_ai_key
        self.model = model or os.getenv("GEMINI_MODEL") or DEFAULT_MODEL
        
        # Determine which endpoint to use based on key type
        # Google AI Studio keys start with "AIza", Vertex keys start with "AQ."
        if self.api_key and self.api_key.startswith("AIza"):
            self.endpoint_type = "genai"  # Google AI Studio
        else:
            self.endpoint_type = "vertex"  # Vertex AI publisher
        
        if not self.api_key:
            raise ValueError("GOOGLE_AI_API_KEY, GEMINI_API_KEY, or GOOGLE_CLOUD_API_KEY environment variable required")
        
        logger.info(f"GeminiClient initialized: model={self.model}, endpoint={self.endpoint_type}")
    
    def _build_url(self, model: str, stream: bool = False) -> str:
        """Build the API endpoint URL based on key type."""
        action = "streamGenerateContent" if stream else "generateContent"
        
        if self.endpoint_type == "genai":
            # Google AI Studio endpoint (v1beta)
            return f"https://{GENAI_ENDPOINT}/v1beta/models/{model}:{action}?key={self.api_key}"
        else:
            # Vertex AI publisher endpoint
            return f"https://{VERTEX_ENDPOINT}/v1/publishers/google/models/{model}:{action}?key={self.api_key}"
    
    def _build_function_declarations(self, tools: List[Callable]) -> List[Dict]:
        """Convert Python functions to Gemini function declarations."""
        import inspect
        import typing
        
        declarations = []
        
        for func in tools:
            # Get function metadata
            name = func.__name__
            doc = func.__doc__ or ""
            
            # Parse type hints for parameters
            sig = inspect.signature(func)
            
            properties = {}
            required = []
            
            for param_name, param in sig.parameters.items():
                if param_name in ("self", "cls"):
                    continue
                
                # Build parameter schema
                param_schema = self._annotation_to_schema(param.annotation, param_name)
                properties[param_name] = param_schema
                
                # Mark as required if no default value
                if param.default == inspect.Parameter.empty:
                    required.append(param_name)
            
            declarations.append({
                "name": name,
                "description": doc.strip().split("\n")[0] if doc else name,  # First line of docstring
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            })
        
        return declarations
    
    def _annotation_to_schema(self, annotation, param_name: str) -> Dict:
        """Convert a Python type annotation to JSON Schema."""
        import inspect
        import typing
        
        # Default schema
        schema = {"type": "string", "description": f"Parameter: {param_name}"}
        
        if annotation == inspect.Parameter.empty:
            return schema
        
        # Handle Optional types (Union[X, None])
        origin = getattr(annotation, "__origin__", None)
        args = getattr(annotation, "__args__", ())
        
        # Check for Optional (Union with None)
        if origin is typing.Union and type(None) in args:
            # Get the non-None type
            real_types = [a for a in args if a is not type(None)]
            if real_types:
                annotation = real_types[0]
                origin = getattr(annotation, "__origin__", None)
                args = getattr(annotation, "__args__", ())
        
        # Handle List types
        if origin is list or (hasattr(typing, 'List') and origin is getattr(typing, 'List', None)):
            item_type = "string"  # default
            if args:
                inner = args[0]
                if inner in (int, float):
                    item_type = "number"
                elif inner == bool:
                    item_type = "boolean"
                elif inner == str:
                    item_type = "string"
            return {
                "type": "array",
                "items": {"type": item_type},
                "description": f"Parameter: {param_name}"
            }
        
        # Handle Dict types
        if origin is dict or (hasattr(typing, 'Dict') and origin is getattr(typing, 'Dict', None)):
            return {
                "type": "object",
                "description": f"Parameter: {param_name}"
            }
        
        # Handle basic types
        if annotation in (int, float):
            return {"type": "number", "description": f"Parameter: {param_name}"}
        elif annotation == bool:
            return {"type": "boolean", "description": f"Parameter: {param_name}"}
        elif annotation == str:
            return {"type": "string", "description": f"Parameter: {param_name}"}
        elif annotation == list:
            return {
                "type": "array",
                "items": {"type": "string"},
                "description": f"Parameter: {param_name}"
            }
        elif annotation == dict:
            return {
                "type": "object",
                "description": f"Parameter: {param_name}"
            }
        
        # Check string representation for typing module types
        ann_str = str(annotation)
        if "List" in ann_str or "list" in ann_str:
            return {
                "type": "array",
                "items": {"type": "number" if "float" in ann_str or "int" in ann_str else "string"},
                "description": f"Parameter: {param_name}"
            }
        
        return schema
    
    def call(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        tools: Optional[List[Callable]] = None,
        tool_executor: Optional[Callable[[str, Dict], Any]] = None,
        temperature: float = 0.1,
        max_tokens: int = 32000,
        model: Optional[str] = None,
        max_tool_iterations: int = 10
    ) -> GeminiResponse:
        """
        Call Gemini with optional function calling.
        
        Args:
            prompt: The user message
            system_instruction: System prompt for the model
            tools: List of Python functions to make available
            tool_executor: Function to execute tool calls: (name, args) -> result
            temperature: Sampling temperature
            max_tokens: Maximum output tokens
            model: Override the default model
            max_tool_iterations: Max rounds of tool calling
            
        Returns:
            GeminiResponse with text or error
        """
        model = model or self.model
        url = self._build_url(model, stream=False)
        
        # Build request body
        body: Dict[str, Any] = {
            "contents": [{
                "role": "user",
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
            "safetySettings": DEFAULT_SAFETY_SETTINGS
        }
        
        # Add system instruction
        if system_instruction:
            body["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }
        
        # Add tools if provided
        if tools:
            body["tools"] = [{
                "functionDeclarations": self._build_function_declarations(tools)
            }]
        
        # Conversation history for multi-turn tool calling
        contents = body["contents"]
        
        try:
            for iteration in range(max_tool_iterations):
                logger.info(f"Calling Gemini ({model}), iteration {iteration + 1}")
                
                response = requests.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json=body,
                    timeout=120
                )
                
                if response.status_code == 429:
                    # Rate limit - wait and retry
                    wait_time = 2 ** iteration
                    logger.warning(f"Rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                
                if not response.ok:
                    return GeminiResponse(
                        success=False,
                        error=f"HTTP {response.status_code}: {response.text[:500]}",
                        model=model
                    )
                
                data = response.json()
                
                # Extract usage
                usage = None
                if "usageMetadata" in data:
                    um = data["usageMetadata"]
                    usage = TokenUsage(
                        prompt_tokens=um.get("promptTokenCount", 0),
                        completion_tokens=um.get("candidatesTokenCount", 0),
                        total_tokens=um.get("totalTokenCount", 0)
                    )
                
                # Check for candidates
                candidates = data.get("candidates", [])
                if not candidates:
                    return GeminiResponse(
                        success=False,
                        error="No candidates in response",
                        raw_response=response.text[:1000],
                        model=model
                    )
                
                candidate = candidates[0]
                parts = candidate.get("content", {}).get("parts", [])
                
                # Check for function calls
                function_calls = []
                text_parts = []
                
                for part in parts:
                    if "functionCall" in part:
                        function_calls.append(part["functionCall"])
                        logger.debug(f"  Found function call: {part['functionCall'].get('name')}")
                    elif "text" in part:
                        text_parts.append(part["text"])
                        logger.debug(f"  Found text part: {part['text'][:100]}...")
                
                logger.info(f"Response parts: {len(function_calls)} function calls, {len(text_parts)} text parts")
                
                # If function calls and we have an executor, execute them
                if function_calls and tool_executor:
                    logger.info(f"Executing {len(function_calls)} function calls")
                    
                    # Add model response to history
                    contents.append({
                        "role": "model",
                        "parts": parts
                    })
                    
                    # Execute each function call
                    function_responses = []
                    for fc in function_calls:
                        fn_name = fc["name"]
                        fn_args = fc.get("args", {})
                        
                        logger.info(f"  Executing: {fn_name}({list(fn_args.keys())})")
                        
                        try:
                            result = tool_executor(fn_name, fn_args)
                            function_responses.append({
                                "functionResponse": {
                                    "name": fn_name,
                                    "response": {"result": result}
                                }
                            })
                        except Exception as e:
                            logger.error(f"  Tool error: {e}")
                            function_responses.append({
                                "functionResponse": {
                                    "name": fn_name,
                                    "response": {"error": str(e)}
                                }
                            })
                    
                    # Add function responses to history
                    contents.append({
                        "role": "user",
                        "parts": function_responses
                    })
                    
                    # Update body with new contents
                    body["contents"] = contents
                    
                    # Continue to next iteration
                    continue
                
                # No function calls or no executor - return text response
                full_text = "".join(text_parts)
                
                if not function_calls:
                    logger.warning(f"No function calls made by model. Text response: {full_text[:200]}...")
                
                return GeminiResponse(
                    success=True,
                    text=full_text,
                    usage=usage,
                    model=model,
                    raw_response=response.text[:500]
                )
            
            # Max iterations reached
            return GeminiResponse(
                success=False,
                error=f"Max tool iterations ({max_tool_iterations}) reached",
                model=model
            )
            
        except requests.exceptions.Timeout:
            return GeminiResponse(
                success=False,
                error="Request timed out after 120 seconds",
                model=model
            )
        except Exception as e:
            logger.error(f"Gemini call failed: {e}")
            return GeminiResponse(
                success=False,
                error=str(e),
                model=model
            )
    
    def simple_call(self, prompt: str, model: Optional[str] = None) -> str:
        """Simple text generation without tools."""
        response = self.call(prompt, model=model)
        if response.success:
            return response.text or ""
        else:
            raise Exception(response.error)
    
    def call_streaming(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        tools: Optional[List[Callable]] = None,
        tool_executor: Optional[Callable[[str, Dict], Any]] = None,
        temperature: float = 0.1,
        max_tokens: int = 32000,
        model: Optional[str] = None,
        max_tool_iterations: int = 10
    ):
        """
        Call Gemini with streaming, yielding events as they happen.
        
        Yields events like:
            {"type": "thinking", "content": "Analyzing request..."}
            {"type": "tool_call", "name": "tool_name", "args": {...}}
            {"type": "tool_result", "name": "tool_name", "result": "..."}
            {"type": "text", "content": "Response text..."}
            {"type": "done", "model": "...", "usage": {...}}
            {"type": "error", "message": "..."}
        """
        model = model or self.model
        url = self._build_url(model, stream=False)  # Non-streaming for tool calls
        
        yield {"type": "thinking", "content": f"Processing with {model}..."}
        
        # Build request body
        body: Dict[str, Any] = {
            "contents": [{
                "role": "user",
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
            "safetySettings": DEFAULT_SAFETY_SETTINGS
        }
        
        if system_instruction:
            body["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }
        
        if tools:
            declarations = self._build_function_declarations(tools)
            logger.info(f"📋 Tool declarations for Gemini: {json.dumps(declarations, indent=2)[:2000]}")
            body["tools"] = [{
                "functionDeclarations": declarations
            }]
        
        contents = body["contents"]
        
        try:
            for iteration in range(max_tool_iterations):
                yield {"type": "thinking", "content": f"Iteration {iteration + 1}..."}
                
                response = requests.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json=body,
                    timeout=120
                )
                
                if response.status_code == 429:
                    wait_time = 2 ** iteration
                    yield {"type": "thinking", "content": f"Rate limited, waiting {wait_time}s..."}
                    time.sleep(wait_time)
                    continue
                
                if not response.ok:
                    yield {"type": "error", "message": f"HTTP {response.status_code}: {response.text[:500]}"}
                    return
                
                data = response.json()
                
                # Extract usage
                usage = None
                if "usageMetadata" in data:
                    um = data["usageMetadata"]
                    usage = {
                        "prompt_tokens": um.get("promptTokenCount", 0),
                        "completion_tokens": um.get("candidatesTokenCount", 0),
                        "total_tokens": um.get("totalTokenCount", 0)
                    }
                
                candidates = data.get("candidates", [])
                if not candidates:
                    yield {"type": "error", "message": "No candidates in response"}
                    return
                
                candidate = candidates[0]
                parts = candidate.get("content", {}).get("parts", [])
                
                function_calls = []
                text_parts = []
                
                for part in parts:
                    if "functionCall" in part:
                        function_calls.append(part["functionCall"])
                    elif "text" in part:
                        text_parts.append(part["text"])
                
                logger.info(f"Response parts: {len(function_calls)} function calls, {len(text_parts)} text parts")
                if text_parts and not function_calls:
                    logger.warning(f"No function calls made by model. Text response: {text_parts[0][:500]}...")
                
                # Execute function calls if any
                if function_calls and tool_executor:
                    # Add model response to history
                    contents.append({
                        "role": "model",
                        "parts": parts
                    })
                    
                    function_responses = []
                    for fc in function_calls:
                        fn_name = fc["name"]
                        fn_args = fc.get("args", {})
                        
                        # Emit tool call event
                        yield {
                            "type": "tool_call",
                            "name": fn_name,
                            "args": fn_args,
                            "status": "running"
                        }
                        
                        try:
                            result = tool_executor(fn_name, fn_args)
                            function_responses.append({
                                "functionResponse": {
                                    "name": fn_name,
                                    "response": {"result": result}
                                }
                            })
                            
                            # Emit tool result event
                            yield {
                                "type": "tool_result",
                                "name": fn_name,
                                "result": result,
                                "status": "success"
                            }
                        except Exception as e:
                            function_responses.append({
                                "functionResponse": {
                                    "name": fn_name,
                                    "response": {"error": str(e)}
                                }
                            })
                            yield {
                                "type": "tool_result",
                                "name": fn_name,
                                "result": str(e),
                                "status": "error"
                            }
                    
                    # Add function responses to history
                    contents.append({
                        "role": "user",
                        "parts": function_responses
                    })
                    
                    body["contents"] = contents
                    continue
                
                # No function calls - emit final text
                full_text = "".join(text_parts)
                if full_text:
                    yield {"type": "text", "content": full_text}
                
                yield {
                    "type": "done",
                    "model": model,
                    "usage": usage
                }
                return
            
            yield {"type": "error", "message": f"Max iterations ({max_tool_iterations}) reached"}
            
        except requests.exceptions.Timeout:
            yield {"type": "error", "message": "Request timed out after 120 seconds"}
        except Exception as e:
            yield {"type": "error", "message": str(e)}


# Singleton client for convenience
_client: Optional[GeminiClient] = None

def get_client() -> GeminiClient:
    """Get or create the singleton Gemini client."""
    global _client
    if _client is None:
        _client = GeminiClient()
    return _client


def call_gemini(
    prompt: str,
    system_instruction: Optional[str] = None,
    tools: Optional[List[Callable]] = None,
    tool_executor: Optional[Callable[[str, Dict], Any]] = None,
    **kwargs
) -> GeminiResponse:
    """Convenience function to call Gemini."""
    return get_client().call(
        prompt,
        system_instruction=system_instruction,
        tools=tools,
        tool_executor=tool_executor,
        **kwargs
    )


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Gemini REST client...")
    
    client = GeminiClient()
    
    # Test simple call
    response = client.call("What is 2+2? Reply with just the number.")
    print(f"\nSimple call:")
    print(f"  Success: {response.success}")
    print(f"  Text: {response.text}")
    print(f"  Model: {response.model}")
    if response.usage:
        print(f"  Tokens: {response.usage.total_tokens}")
        print(f"  Est. cost: ${response.usage.estimated_cost:.6f}")

