"""
Factory for creating Langroid agents with appropriate configuration.
"""
import os
import logging
from typing import Optional

import langroid as lr
from langroid.agent.chat_agent import ChatAgent, ChatAgentConfig
from langroid.language_models import MockLMConfig
from langroid.language_models.openai_gpt import OpenAIGPTConfig

logger = logging.getLogger(__name__)


def create_agent(
    name: str = "Assistant",
    system_message: Optional[str] = None,
    use_mock: Optional[bool] = None
) -> ChatAgent:
    """
    Create a Langroid ChatAgent with appropriate LLM configuration.
    
    Args:
        name: Name for the agent
        system_message: Custom system message (uses default if None)
        use_mock: Force mock LLM (auto-detects from env if None)
        
    Returns:
        Configured ChatAgent instance
    """
    # Determine if we should use mock LLM
    if use_mock is None:
        use_mock = os.getenv("USE_MOCK_LLM", "").lower() in ["true", "1", "yes"]
        openai_key = os.getenv("OPENAI_API_KEY")
        use_mock = use_mock or not openai_key
    
    # Default system message
    if system_message is None:
        system_message = """You are a helpful AI assistant powered by Langroid, 
        communicating through a web interface. Be concise, friendly, and helpful."""
    
    # Create appropriate LLM config
    if use_mock:
        logger.info("Creating agent with MockLM")
        llm_config = MockLMConfig(
            stream=False,  # Disable streaming for callback compatibility
            response_dict={
                "hello": "Hello! I'm a Langroid agent ready to help you. How can I assist you today?",
                "hi": "Hi there! I'm your AI assistant powered by Langroid. What would you like to talk about?",
                "help": "I can help you with:\n• General conversation\n• Answering questions\n• Problem solving\n• Code assistance\n• And much more!\n\nWhat would you like to explore?",
                "test": "Great! The chat interface is working perfectly. I'm receiving your messages and responding through the WebSocket connection.",
                "langroid": "Langroid is the powerful framework that enables me to have this conversation with you! It provides:\n• Agent-based architecture\n• Tool usage capabilities\n• Multi-agent orchestration\n• And seamless web integration like you're experiencing now!",
                "bye|goodbye": "Goodbye! It was great chatting with you. Feel free to return anytime!",
                "default": "I understand. I'm here to help with whatever you need. Feel free to ask me anything!"
            },
            default_response="I'm here to help! As a Langroid-powered assistant, I can engage in conversations on many topics."
        )
    else:
        logger.info("Creating agent with OpenAI GPT")
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        llm_config = OpenAIGPTConfig(
            chat_model=model,
            chat_context_length=16000,
            stream=False,  # Disable streaming for callback compatibility
            temperature=0.7,
        )
    
    # Create agent config
    config = ChatAgentConfig(
        name=name,
        llm=llm_config,
        system_message=system_message,
        show_stats=False,  # Don't show token stats in UI
    )
    
    # Create and return agent
    agent = ChatAgent(config)
    logger.info(f"Created agent '{name}' with {type(llm_config).__name__}")
    
    return agent