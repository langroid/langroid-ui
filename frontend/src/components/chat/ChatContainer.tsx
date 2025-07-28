import { useEffect, useRef, useState } from 'react';
import type { Message } from '../../types';
import { ChatMessage } from './ChatMessage';
import { ChatInput } from './ChatInput';
import { Loader2 } from 'lucide-react';

interface ChatContainerProps {
  sessionId?: string;
}

export function ChatContainer({ sessionId }: ChatContainerProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [streamingMessages, setStreamingMessages] = useState<Map<string, string>>(new Map());
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Auto-scroll to bottom when new messages arrive
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // WebSocket connection
  useEffect(() => {
    try {
      const ws = new WebSocket('ws://localhost:8000/ws');
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('WebSocket connected');
        setIsConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          console.log('Received message:', data);
          
          if (data.type === 'message') {
            setMessages(prev => [...prev, data.message]);
            setIsLoading(false);
          } else if (data.type === 'stream_start') {
            // Start a new streaming message
            const message: Message = {
              id: data.message_id,
              content: '',
              sender: data.sender || 'assistant',
              timestamp: new Date(),
            };
            setMessages(prev => [...prev, message]);
            setStreamingMessages(prev => new Map(prev).set(data.message_id, ''));
            setIsLoading(false);
          } else if (data.type === 'stream_token') {
            // Add token to streaming message
            setStreamingMessages(prev => {
              const newMap = new Map(prev);
              const currentContent = newMap.get(data.message_id) || '';
              newMap.set(data.message_id, currentContent + data.token);
              return newMap;
            });
            // Update message content
            setMessages(prev => prev.map(msg => 
              msg.id === data.message_id 
                ? { ...msg, content: (streamingMessages.get(data.message_id) || '') + data.token }
                : msg
            ));
          } else if (data.type === 'stream_end') {
            // Finalize streaming message
            const finalContent = streamingMessages.get(data.message_id) || '';
            setMessages(prev => prev.map(msg => 
              msg.id === data.message_id 
                ? { ...msg, content: finalContent }
                : msg
            ));
            setStreamingMessages(prev => {
              const newMap = new Map(prev);
              newMap.delete(data.message_id);
              return newMap;
            });
          } else if (data.type === 'input_request') {
            // Show system message for input request
            const message: Message = {
              id: Date.now().toString(),
              content: data.prompt || 'Waiting for your input...',
              sender: 'system',
              timestamp: new Date(),
            };
            setMessages(prev => [...prev, message]);
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
        console.log('WebSocket disconnected');
        setIsConnected(false);
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        setIsConnected(false);
      };

      return () => {
        ws.close();
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
      wsRef.current.send(JSON.stringify({
        type: 'message',
        content,
        sessionId,
      }));
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
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center">
                <Loader2 className="w-5 h-5 text-blue-600 animate-spin" />
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
      <ChatInput onSend={handleSendMessage} disabled={!isConnected || isLoading} />
    </div>
  );
}