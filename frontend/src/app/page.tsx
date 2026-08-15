'use client';

import AppDrawer from '@/components/AppDrawer';
import ChatInput from '@/components/ChatInput';
import ChatInterface from '@/components/ChatInterface';
import ConfirmationModal from '@/components/ConfirmationModal';
import DataSourceFilter, { DataSourceType } from '@/components/DataSourceFilter';
import { DarkModeButton, DisclaimerModal, InfoButton } from '@/components/Disclaimer';
import SupportButton from '@/components/SupportButton';
import { clearSession, sendMessageStream, submitFeedback, uploadDocument } from '@/services/api';
import { getSessionId } from '@/services/session';
import { Bars3Icon } from '@heroicons/react/24/outline';
import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useEffect, useMemo, useRef, useState } from 'react';

const WELCOME_MESSAGE = `Bonjour ! Je suis Turgot, votre assistant pour les démarches administratives françaises. 🏛️

Je peux vous répondre à vos questions à propos des documents d'identité, des impôts, des élections, du logement, etc. et vous citerai les sources utilisées.\n
Voici un exemple de question: "Quel est le prix de renouvellement d'une carte d'identité en cas de perte?"

Mes sources sont :

- **👤 Les droits des particuliers** ([vosdroits.service-public.fr](https://vosdroits.service-public.fr))
- **💼 Les démarches pour professionnels** ([entreprendre.service-public.fr](https://entreprendre.service-public.fr))

Utilisez le filtre en haut à droite pour afficher uniquement ce qui vous intéresse !

Comment puis-je vous aider aujourd\'hui ?`;

type Source = {
  url: string;
  title: string;
  excerpt: string;
  data_source?: string;
};

type ChatMessage = {
  id: string;
  content: string;
  isUser: boolean;
  isStreaming?: boolean;
  sources?: Source[];
  secondarySources?: Source[];
  isError?: boolean;
  feedback?: 1 | -1 | null;
};

export default function Home() {
  const t = useTranslations('ui');
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: '1',
      content: WELCOME_MESSAGE,
      isUser: false,
    },
  ]);
  const [isLoading, setIsLoading] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [isResetModalOpen, setIsResetModalOpen] = useState(false);
  const [isDisclaimerOpen, setIsDisclaimerOpen] = useState(false);
  const [dataSourceFilter, setDataSourceFilter] = useState<DataSourceType>('all');
  const [uploadStatus, setUploadStatus] = useState<string>('');
  const [isUploadConsentOpen, setIsUploadConsentOpen] = useState(false);
  const [pendingUploadFile, setPendingUploadFile] = useState<File | null>(null);
  const uploadInputRef = useRef<HTMLInputElement>(null);

  // Clear session history on page load/refresh for privacy
  useEffect(() => {
    const clearHistoryOnLoad = async () => {
      try {
        const sessionId = getSessionId();
        if (sessionId) {
          // Clear the previous session from backend
          await clearSession();
        }
        // Generate a new session ID
        const newSessionId = crypto.randomUUID();
        localStorage.setItem('turgot_session_id', newSessionId);
        localStorage.setItem('turgot_last_activity', Date.now().toString());
      } catch (error) {
        console.error('Error clearing history on load:', error);
      }
    };
    
    clearHistoryOnLoad();
  }, []);

  // Filter messages based on data source filter
  const filteredMessages = useMemo(() => {
    if (dataSourceFilter === 'all') return messages;

    return messages.map(message => {
      if (message.isUser) return message;

      // Extract sources from message content
      const sourceMatches = message.content.match(/\[([^\]]+)\]\(([^)]+)\)/g);
      const sources = sourceMatches ? sourceMatches.map(match => {
        const [, title, url] = match.match(/\[([^\]]+)\]\(([^)]+)\)/) || [];
        return { url, title: title || url };
      }) : [];

      // Check if message has sources matching the filter
      const hasMatchingSources = sources.some(source => {
        if (dataSourceFilter === 'particuliers') {
          return source.url.includes('vosdroits');
        } else if (dataSourceFilter === 'professionnels') {
          return source.url.includes('entreprendre');
        }
        return false;
      });

      // If no sources or no matching sources, hide the message
      if (sources.length === 0 || !hasMatchingSources) {
        return { ...message, content: '**Message filtré** - Cette réponse ne contient pas de sources pour le type sélectionné.' };
      }

      return message;
    });
  }, [messages, dataSourceFilter]);

  const handleSendMessage = async (message: string) => {
    if (!message.trim()) return;

    const newMessage = {
      id: Date.now().toString(),
      content: message,
      isUser: true,
      feedback: null,
    };

    setMessages((prev) => [...prev, newMessage]);
    setIsLoading(false);
    setIsStreaming(true);

    try {
      const assistantId = (Date.now() + 1).toString();
      // Append an empty assistant message that will be filled progressively
      setMessages((prev) => [...prev, { id: assistantId, content: '', isUser: false, isStreaming: true, feedback: null }]);

      await sendMessageStream(
        message,
        (delta) => {
          setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, content: (m.content || '') + delta } : m)));
        },
        (sources) => {
          setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, sources } : m)));
        }
      );
      // Mark message as no longer streaming
      setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, isStreaming: false } : m)));
    } catch (error) {
      console.error('Error sending message:', error);
      const errorMessage = {
        id: (Date.now() + 1).toString(),
        content: 'Désolé, une erreur est survenue. Veuillez réessayer.',
        isUser: false,
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsStreaming(false);
    }
  };

  const handleExportPDF = async () => {
    const sessionId = getSessionId();
    if (!sessionId) {
      console.error('No session ID found');
      return;
    }

    setIsExporting(true);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || (typeof window !== 'undefined' && window.location.hostname === 'localhost' ? 'http://localhost:8000' : '/api');
      const requestUrl = `${apiUrl}/generate-pdf`;
      
      // First, request PDF generation
      const response = await fetch(requestUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ session_id: sessionId }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        console.error('Response error text:', errorText);
        throw new Error(`Failed to export PDF: ${response.status} ${response.statusText}`);
      }

      // Get the PDF URL from the JSON response
      const data = await response.json();
      const pdfUrl = data.pdf_url;
      
      if (!pdfUrl) {
        throw new Error('No PDF URL received');
      }

      const fullPdfUrl = `${apiUrl}${pdfUrl}`;

      // Download the actual PDF file
      const pdfResponse = await fetch(fullPdfUrl);
      
      if (!pdfResponse.ok) {
        throw new Error('Failed to download PDF');
      }

      // Get the blob from the PDF response
      const blob = await pdfResponse.blob();
      
      // Create a download link
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `turgot_chat_${sessionId}.pdf`;
      document.body.appendChild(a);
      a.click();
      
      // Cleanup
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (error) {
      console.error('Error exporting PDF:', error);
      alert('Une erreur est survenue lors de l\'export du PDF. Veuillez réessayer.');
    } finally {
      setIsExporting(false);
    }
  };

  const handleReset = async () => {
    try {
      // Clear the current session from the backend
      await clearSession();
      
      // Generate a new session ID to ensure complete privacy
      const newSessionId = crypto.randomUUID();
      localStorage.setItem('turgot_session_id', newSessionId);
      localStorage.setItem('turgot_last_activity', Date.now().toString());
      
      // Reset the UI to show only the welcome message
      setMessages([
        {
          id: '1',
          content: WELCOME_MESSAGE,
          isUser: false,
        },
      ]);
      setIsResetModalOpen(false);
    } catch (error) {
      console.error('Error resetting session:', error);
      // You might want to show an error message to the user here
    }
  };

  const handleSupport = () => {
    window.open('https://www.buymeacoffee.com/louischirol', '_blank');
  };
  const handleGitHub = () => {
    window.open('https://github.com/LouisChirol/TurgotChat', '_blank');
  };

  const handleFeedback = async (messageId: string, value: 1 | -1) => {
    const targetMessage = messages.find((message) => message.id === messageId);
    setMessages((prev) => prev.map((message) => (message.id === messageId ? { ...message, feedback: value } : message)));
    try {
      await submitFeedback(messageId, value, targetMessage?.content.slice(0, 300) || '');
    } catch (error) {
      console.error('Error submitting feedback:', error);
    }
  };

  const handleUploadClick = () => {
    uploadInputRef.current?.click();
  };

  const handleUploadFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setPendingUploadFile(file);
    setIsUploadConsentOpen(true);
    event.target.value = '';
  };

  const handleConfirmUpload = async () => {
    if (!pendingUploadFile) return;
    try {
      const response = await uploadDocument(pendingUploadFile, true);
      setUploadStatus(response.message);
    } catch (error) {
      console.error('Error uploading document:', error);
      const message = error instanceof Error ? error.message : 'Erreur lors du téléversement';
      setUploadStatus(message);
    } finally {
      setPendingUploadFile(null);
      setIsUploadConsentOpen(false);
    }
  };

  return (
    <main className="flex flex-col h-[100dvh]">
      <header className="shrink-0 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 transition-colors duration-200">
        <div className="max-w-4xl mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Image
                src="/turgot_v2.png"
                alt="Turgot Assistant"
                width={60}
                height={60}
                className="rounded-full"
              />
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="text-2xl font-bold dark:text-white">Turgot</h1>
                  <div className="w-6 h-4 flex overflow-hidden rounded-sm shadow-sm">
                    <div className="flex-1 bg-blue-600"></div>
                    <div className="flex-1 bg-white"></div>
                    <div className="flex-1 bg-red-600"></div>
                  </div>
                </div>
                <p className="text-sm text-gray-600 dark:text-gray-300">{t('assistantTagline')}</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <DataSourceFilter 
                activeFilter={dataSourceFilter}
                onFilterChange={setDataSourceFilter}
                className="hidden sm:block"
              />
              <InfoButton onClick={() => setIsDisclaimerOpen(true)} />
              <DarkModeButton />
              <button
                onClick={() => setIsDrawerOpen(true)}
                className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
                aria-label={t('openMenu')}
              >
                <Bars3Icon className="h-7 w-7 text-gray-700 dark:text-gray-200" />
              </button>
            </div>
          </div>
          {/* Mobile data source filter */}
          <div className="mt-3 sm:hidden">
            <DataSourceFilter 
              activeFilter={dataSourceFilter}
              onFilterChange={setDataSourceFilter}
            />
          </div>
        </div>
      </header>

      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-4xl mx-auto px-4 py-4">
            <ChatInterface messages={filteredMessages} isLoading={false} onFeedback={handleFeedback} />
          </div>
        </div>

        <SupportButton />

        <div className="shrink-0 bg-white dark:bg-gray-800 border-t border-gray-200 dark:border-gray-700 pb-safe transition-colors duration-200">
          <div className="h-1 flex max-w-4xl mx-auto">
            <div className="flex-1 bg-blue-600"></div>
            <div className="flex-1 bg-white"></div>
            <div className="flex-1 bg-red-600"></div>
          </div>
          <div className="max-w-4xl mx-auto px-4 py-4">
            <div className="mb-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-100">
              {t('uploadConsentWarning')}
            </div>
            <div className="mb-3 flex items-center gap-2">
              <button
                type="button"
                onClick={handleUploadClick}
                className="rounded-md border border-gray-300 dark:border-gray-600 px-3 py-2 text-sm text-gray-800 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              >
                {t('uploadButton')}
              </button>
              {uploadStatus && <p className="text-xs text-gray-700 dark:text-gray-300">{uploadStatus}</p>}
              <input
                ref={uploadInputRef}
                type="file"
                accept="application/pdf"
                className="hidden"
                onChange={handleUploadFile}
              />
            </div>
            <ChatInput
              onSendMessage={handleSendMessage}
              isLoading={isStreaming}
              placeholder={t('chatPlaceholder')}
              sendLabel={t('sendMessage')}
              micStartLabel={t('micStart')}
              micStopLabel={t('micStop')}
            />
          </div>
        </div>
      </div>

      <AppDrawer
        open={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        onExportPDF={handleExportPDF}
        onClear={() => setIsResetModalOpen(true)}
        onSupport={handleSupport}
        onGitHub={handleGitHub}
        isExporting={isExporting}
        isClearing={isLoading}
        disableExport={isExporting || isLoading || messages.length <= 1}
        disableClear={isLoading || messages.length <= 1}
      />

      <ConfirmationModal
        isOpen={isResetModalOpen}
        onClose={() => setIsResetModalOpen(false)}
        onConfirm={handleReset}
        title={t('resetTitle')}
        message={t('resetMessage')}
        confirmText={t('resetConfirm')}
        cancelText={t('cancel')}
      />

      <DisclaimerModal
        isOpen={isDisclaimerOpen}
        onClose={() => setIsDisclaimerOpen(false)}
      />

      {isUploadConsentOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-labelledby="upload-consent-title">
          <div className="w-full max-w-lg rounded-lg bg-white p-6 shadow-xl dark:bg-gray-900">
            <h2 id="upload-consent-title" className="mb-3 text-lg font-semibold text-gray-900 dark:text-gray-100">
              {t('consentTitle')}
            </h2>
            <p className="mb-5 text-sm text-gray-700 dark:text-gray-300">
              {t('consentMessage')}
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setPendingUploadFile(null);
                  setIsUploadConsentOpen(false);
                }}
                className="rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-600"
              >
                {t('cancel')}
              </button>
              <button
                type="button"
                onClick={handleConfirmUpload}
                className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700"
              >
                {t('consentConfirm')}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
} 