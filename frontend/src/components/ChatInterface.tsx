'use client';

import Message from '@/components/Message';
import Image from 'next/image';
import { useEffect, useRef } from 'react';

interface Message {
    id: string;
    content: string;
    isUser: boolean;
    isStreaming?: boolean;
    sources?: Array<{
        url: string;
        title: string;
        excerpt: string;
    }>;
    secondarySources?: Array<{
        url: string;
        title: string;
        excerpt: string;
    }>;
    isError?: boolean;
    feedback?: 1 | -1 | null;
}

interface ChatInterfaceProps {
    messages: Message[];
    isLoading: boolean;
    onFeedback?: (messageId: string, value: 1 | -1) => void;
}

const ChatInterface = ({ messages, isLoading, onFeedback }: ChatInterfaceProps) => {
    const messagesEndRef = useRef<HTMLDivElement>(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages, isLoading]);

    const hasStreamingEmpty = messages.some(
        (m) => !m.isUser && m.isStreaming && (!m.content || m.content.trim() === '')
    );

    return (
        <div className="flex flex-col h-full">
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {messages
                    .filter(
                        (message) =>
                            !(
                                !message.isUser &&
                                message.isStreaming &&
                                (!message.content || message.content.trim() === '')
                            )
                    )
                    .map((message) => (
                        <Message
                            key={message.id}
                            messageId={message.id}
                            role={message.isUser ? 'user' : 'assistant'}
                            content={message.content}
                            isStreaming={message.isStreaming}
                            sources={message.sources}
                            secondarySources={message.secondarySources}
                            isError={message.isError}
                            feedback={message.feedback}
                            onFeedback={onFeedback}
                        />
                    ))}
                {(isLoading || hasStreamingEmpty) && (
                    <div className="flex justify-start gap-3" aria-live="polite" aria-label="Réponse en cours de génération">
                        <div className="w-12 h-12 rounded-full overflow-hidden flex-shrink-0">
                            <Image
                                src="/turgot_thinking.png"
                                alt="Turgot Thinking"
                                width={48}
                                height={48}
                                className="w-full h-full object-cover"
                            />
                        </div>
                        <div className="max-w-[80%] rounded-lg p-4 bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200 transition-colors duration-200">
                            <div className="flex space-x-2">
                                <div className="w-2 h-2 bg-gray-400 dark:bg-gray-500 rounded-full animate-bounce"></div>
                                <div className="w-2 h-2 bg-gray-400 dark:bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                                <div className="w-2 h-2 bg-gray-400 dark:bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '0.4s' }}></div>
                            </div>
                        </div>
                    </div>
                )}
                <div ref={messagesEndRef} />
            </div>
        </div>
    );
};

export default ChatInterface; 