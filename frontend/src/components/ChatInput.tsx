'use client';

import { Loader2, Mic, MicOff, Send } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useAudioRecorder } from '../hooks/useAudioRecorder';

interface ChatInputProps {
  onSendMessage: (content: string) => void;
  disabled?: boolean;
  isLoading?: boolean;
  placeholder?: string;
  sendLabel?: string;
  micStartLabel?: string;
  micStopLabel?: string;
}

const ChatInput = ({
  onSendMessage,
  disabled = false,
  isLoading = false,
  placeholder = 'Posez votre question...',
  sendLabel = 'Envoyer le message',
  micStartLabel = "Commencer la dictée vocale",
  micStopLabel = "Arrêter l'enregistrement",
}: ChatInputProps) => {
  const [message, setMessage] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const {
    isRecording,
    isTranscribing,
    startRecording,
    stopRecording,
    error,
    clearError,
  } = useAudioRecorder();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (message.trim() && !disabled && !isLoading) {
      onSendMessage(message);
      setMessage('');
      // Reset textarea height
      if (textareaRef.current) {
        textareaRef.current.style.height = '44px';
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const adjustTextareaHeight = () => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = '44px'; // Reset to min height
      textarea.style.height = `${Math.min(textarea.scrollHeight, 150)}px`;
    }
  };

  useEffect(() => {
    adjustTextareaHeight();
  }, [message]);

  const handleMicClick = async () => {
    if (isRecording) {
      const transcribedText = await stopRecording();
      if (transcribedText) {
        setMessage(transcribedText);
      }
    } else {
      await startRecording();
    }
  };

  // Show error toast
  useEffect(() => {
    if (error) {
      // You can replace this with a proper toast library
      alert(error);
      clearError();
    }
  }, [error, clearError]);

  return (
    <form onSubmit={handleSubmit} className="chat-input flex items-center gap-2">
      <div className="flex-1">
        <label htmlFor="chat-input-textarea" className="sr-only">
          Zone de saisie du message
        </label>
        <textarea
          id="chat-input-textarea"
          ref={textareaRef}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          className={`w-full p-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none min-h-[44px] bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400 transition-colors duration-200 ${
            disabled || isLoading ? 'bg-gray-100 dark:bg-gray-600 cursor-not-allowed' : ''
          }`}
          disabled={disabled || isLoading}
          rows={1}
          aria-multiline="true"
          onFocus={() => {
            setTimeout(() => {
              textareaRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
            }, 100);
          }}
        />
      </div>
      
      {/* Microphone Button */}
      <button
        type="button"
        onClick={handleMicClick}
        className={`p-3 rounded-lg transition-all min-h-[44px] min-w-[44px] flex items-center justify-center relative group ${
          isRecording 
            ? 'bg-red-500 text-white hover:bg-red-600 dark:bg-red-600 dark:hover:bg-red-700 animate-pulse' 
            : isTranscribing
            ? 'bg-gray-400 text-white cursor-not-allowed'
            : 'bg-gray-200 text-gray-600 hover:bg-gray-300 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600'
        } ${
          disabled || isLoading ? 'opacity-50 cursor-not-allowed' : ''
        }`}
        disabled={disabled || isLoading || isTranscribing}
        aria-label={isRecording ? micStopLabel : micStartLabel}
      >
        {isTranscribing ? (
          <Loader2 className="h-5 w-5 animate-spin" />
        ) : isRecording ? (
          <MicOff className="h-5 w-5" />
        ) : (
          <Mic className="h-5 w-5" />
        )}
        <span className="absolute left-1/2 -translate-x-1/2 top-full mt-2 bg-gray-900 dark:bg-gray-700 text-white text-sm py-1 px-2 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap z-10">
          {isRecording ? micStopLabel : isTranscribing ? "Transcription en cours..." : "Dictée vocale"}
        </span>
      </button>
      <button
        type="submit"
        className={`p-3 rounded-lg bg-blue-500 text-white hover:bg-blue-600 dark:bg-blue-600 dark:hover:bg-blue-700 transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center relative group ${
          disabled || isLoading ? 'opacity-50 cursor-not-allowed' : ''
        }`}
        disabled={disabled || isLoading}
        aria-label={sendLabel}
      >
        <Send className="h-5 w-5" />
        <span className="absolute left-1/2 -translate-x-1/2 top-full mt-2 bg-gray-900 dark:bg-gray-700 text-white text-sm py-1 px-2 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap z-10">
          {sendLabel}
        </span>
      </button>
    </form>
  );
};

export default ChatInput; 