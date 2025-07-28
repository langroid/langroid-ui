import type { Message } from '../../types';
import { User, Bot } from 'lucide-react';
import { clsx } from 'clsx';
import ReactMarkdown from 'react-markdown';

interface ChatMessageProps {
  message: Message;
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.sender === 'user';
  const isSystem = message.sender === 'system';
  
  return (
    <div className={clsx(
      'flex gap-3 px-4 py-2',
      isUser ? 'justify-end' : 'justify-start'
    )}>
      {!isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center">
          <Bot className="w-5 h-5 text-blue-600" />
        </div>
      )}
      
      <div className={clsx(
        'max-w-[70%] rounded-lg px-4 py-2',
        isUser 
          ? 'bg-blue-500 text-white' 
          : 'bg-gray-100 text-gray-900'
      )}>
        {isUser || isSystem ? (
          <p className="whitespace-pre-wrap break-words">{message.content}</p>
        ) : (
          <div className="prose prose-sm max-w-none">
            <ReactMarkdown>{message.content}</ReactMarkdown>
          </div>
        )}
        <span className={clsx(
          'text-xs mt-1 block',
          isUser ? 'text-blue-100' : 'text-gray-500'
        )}>
          {new Date(message.timestamp).toLocaleTimeString()}
        </span>
      </div>
      
      {isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center">
          <User className="w-5 h-5 text-gray-600" />
        </div>
      )}
    </div>
  );
}