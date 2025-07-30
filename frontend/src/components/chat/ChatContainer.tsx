import { useEffect, useRef, useState } from 'react';
import type { Message } from '../../types';
import { ChatMessage } from './ChatMessage';
import { ChatInput, type ChatInputRef } from './ChatInput';

// Generate a stable browser session ID that survives React StrictMode rerenders
// Use a global variable to ensure same ID across renders in the same page load
let globalBrowserSessionId = '';
const getBrowserSessionId = () => {
  const key = 'langroid-browser-session-id';
  
  // First check if we already have it in memory for this page load
  if (globalBrowserSessionId) {
    return globalBrowserSessionId;
  }
  
  // Then check sessionStorage
  let sessionId = sessionStorage.getItem(key);
  if (!sessionId) {
    sessionId = `browser-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    sessionStorage.setItem(key, sessionId);
  }
  
  // Store in memory so both React StrictMode renders use the same ID
  globalBrowserSessionId = sessionId;
  return sessionId;
};

interface ChatContainerProps {
  sessionId?: string;
}

export function ChatContainer({ sessionId }: ChatContainerProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [_streamingMessages, setStreamingMessages] = useState<Map<string, string>>(new Map());
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const inputRef = useRef<ChatInputRef | null>(null);
  const connectionRef = useRef<boolean>(false);
  
  // Store message IDs in state so they persist across reconnections AND React re-mounts
  const getPersistedMessageIds = (): Set<string> => {
    try {
      const stored = sessionStorage.getItem('langroid_message_ids');
      if (stored) {
        const idsArray = JSON.parse(stored);
        return new Set(idsArray);
      }
    } catch (error) {
      console.warn('Failed to load persisted message IDs:', error);
    }
    return new Set();
  };

  const [messageIds, setMessageIds] = useState<Set<string>>(getPersistedMessageIds);
  
  // Use a ref for synchronous deduplication to prevent race conditions
  const messageIdsRef = useRef<Set<string>>(getPersistedMessageIds());

  // Persist message IDs to sessionStorage whenever they change
  useEffect(() => {
    try {
      const idsArray = Array.from(messageIds);
      sessionStorage.setItem('langroid_message_ids', JSON.stringify(idsArray));
      // Keep ref in sync
      messageIdsRef.current = new Set(messageIds);
    } catch (error) {
      console.warn('Failed to persist message IDs:', error);
    }
  }, [messageIds]);

  // Auto-scroll to bottom when new messages arrive
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // WebSocket connection
  useEffect(() => {
    // Prevent duplicate connections
    if (connectionRef.current) {
      console.log('WebSocket connection already exists, skipping');
      return;
    }
    
    try {
      connectionRef.current = true;
      const browserSessionId = getBrowserSessionId();
      console.log(`Creating WebSocket connection for browser session: ${browserSessionId}`);
      const ws = new WebSocket(`ws://localhost:8000/ws?browser_session_id=${browserSessionId}`);
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        // Focus input on initial connection
        setTimeout(() => inputRef.current?.focus(), 200);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'message') {
            // Backend sends CompleteMessage with nested message object
            const message: Message = {
              id: data.message.id,
              content: data.message.content,
              sender: data.message.sender,
              timestamp: new Date(data.message.timestamp),
            };
            
            // Deduplicate messages by ID using ref for synchronous check
            if (!messageIdsRef.current.has(message.id)) {
              console.log(`📥 New message: ${message.id} - ${message.content.substring(0, 50)}...`);
              messageIdsRef.current.add(message.id);
              setMessageIds(prev => new Set([...prev, message.id]));
              setMessages(prev => [...prev, message]);
            } else {
              console.warn(`🚫 Duplicate message blocked: ${message.id} - ${message.content.substring(0, 50)}...`);
            }
            setIsLoading(false);
            
            // Focus input after assistant message
            if (message.sender === 'assistant') {
              setTimeout(() => inputRef.current?.focus(), 100);
            }
          } else if (data.type === 'stream_start') {
            // Start a new streaming message (with synchronous deduplication)
            if (!messageIdsRef.current.has(data.message_id)) {
              messageIdsRef.current.add(data.message_id);
              setMessageIds(prev => new Set([...prev, data.message_id]));
              const message: Message = {
                id: data.message_id,
                content: '',
                sender: data.sender || 'assistant',
                timestamp: new Date(),
              };
              setMessages(prev => [...prev, message]);
              setStreamingMessages(prev => new Map(prev).set(data.message_id, ''));
              setIsLoading(false);
            }
          } else if (data.type === 'stream_token') {
            // Add token to streaming message
            setStreamingMessages(prev => {
              const newMap = new Map(prev);
              const currentContent = newMap.get(data.message_id) || '';
              const newContent = currentContent + data.token;
              newMap.set(data.message_id, newContent);
              
              // Update message content with the accumulated content
              setMessages(messages => messages.map(msg => 
                msg.id === data.message_id 
                  ? { ...msg, content: newContent }
                  : msg
              ));
              
              return newMap;
            });
          } else if (data.type === 'stream_end') {
            // Stream has ended, just clean up the streaming state
            // The content is already in the message from the stream_token updates
            setStreamingMessages(prev => {
              const newMap = new Map(prev);
              newMap.delete(data.message_id);
              return newMap;
            });
            
            // Focus input after streaming completes
            setTimeout(() => inputRef.current?.focus(), 100);
          } else if (data.type === 'delete_message') {
            // Remove a message (used for empty streaming bubbles)
            setMessages(prev => prev.filter(msg => msg.id !== data.message_id));
            setStreamingMessages(prev => {
              const newMap = new Map(prev);
              newMap.delete(data.message_id);
              return newMap;
            });
          } else if (data.type === 'input_request') {
            // We no longer show input requests as messages
            // The UI has a persistent input field
            setIsLoading(false);
          } else if (data.type === 'connection') {
            console.log('Connection status:', data);
            // Could show a system message here if desired
          }
        } catch (error) {
          console.error('Error parsing message:', error);
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        connectionRef.current = false; // Allow reconnection after close
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        setIsConnected(false);
      };

      return () => {
        // Only close if WebSocket is actually open
        // This prevents issues with React StrictMode
        if (ws.readyState === WebSocket.OPEN) {
          ws.close();
        }
      };
    } catch (error) {
      console.error('Error creating WebSocket:', error);
    }
  }, []);

  const handleSendMessage = (content: string) => {
    const message: Message = {
      id: Date.now().toString(),
      content,
      sender: 'user',
      timestamp: new Date(),
    };

    setMessages(prev => [...prev, message]);
    setIsLoading(true);

    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      const messageData = {
        type: 'message',
        content,
        sessionId,
      };
      wsRef.current.send(JSON.stringify(messageData));
    }
  };

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b px-4 py-3">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <h1 className="text-xl font-semibold">Langroid Chat</h1>
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} />
            <span className="text-sm text-gray-600">
              {isConnected ? 'Connected' : 'Disconnected'}
            </span>
          </div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto py-4">
          {messages.length === 0 ? (
            <div className="text-center text-gray-500 mt-8">
              <p>Start a conversation by typing a message below</p>
            </div>
          ) : (
            <>
              {messages.map((message) => (
                <ChatMessage key={message.id} message={message} />
              ))}
            </>
          )}
          {isLoading && (
            <div className="flex gap-3 px-4 py-2">
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-500 flex items-center justify-center">
                <span className="text-white text-xs font-semibold">AI</span>
              </div>
              <div className="bg-gray-100 rounded-lg px-4 py-2">
                <div className="flex gap-1">
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }} />
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }} />
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <ChatInput ref={inputRef} onSend={handleSendMessage} disabled={!isConnected || isLoading} />
    </div>
  );
}