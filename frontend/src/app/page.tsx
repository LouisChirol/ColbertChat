'use client';

import AppDrawer from '@/components/AppDrawer';
import ChatInput from '@/components/ChatInput';
import ChatInterface from '@/components/ChatInterface';
import ConfirmationModal from '@/components/ConfirmationModal';
import { DarkModeButton, DisclaimerModal, InfoButton } from '@/components/Disclaimer';
import SupportButton from '@/components/SupportButton';
import { clearSession, sendMessageStream, submitFeedback } from '@/services/api';
import { getSessionId } from '@/services/session';
import { Bars3Icon } from '@heroicons/react/24/outline';
import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

const WELCOME_MESSAGE = `Bonjour ! Je suis Turgot — démarches administratives et fiscalité, avec **sources officielles** citées sous chaque réponse.

**Particuliers** · **Professionnels** · **Doctrine fiscale** (BOFiP)

Exemple : « Quel taux de TVA pour une prestation de photographie ? »`;

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

  // Clear session history on page load/refresh for privacy
  useEffect(() => {
    const clearHistoryOnLoad = async () => {
      try {
        const sessionId = getSessionId();
        if (sessionId) {
          await clearSession();
        }
        const newSessionId = crypto.randomUUID();
        localStorage.setItem('turgot_session_id', newSessionId);
        localStorage.setItem('turgot_last_activity', Date.now().toString());
      } catch (error) {
        console.error('Error clearing history on load:', error);
      }
    };

    clearHistoryOnLoad();
  }, []);

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
      setMessages((prev) => [
        ...prev,
        { id: assistantId, content: '', isUser: false, isStreaming: true, feedback: null },
      ]);

      await sendMessageStream(
        message,
        (delta) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: (m.content || '') + delta } : m
            )
          );
        },
        (sources) => {
          setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, sources } : m)));
        }
      );
      setMessages((prev) =>
        prev.map((m) => (m.id === assistantId ? { ...m, isStreaming: false } : m))
      );
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
      const apiUrl =
        process.env.NEXT_PUBLIC_API_URL ||
        (typeof window !== 'undefined' && window.location.hostname === 'localhost'
          ? 'http://localhost:8000'
          : '/api');
      const requestUrl = `${apiUrl}/generate-pdf`;

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

      const data = await response.json();
      const pdfUrl = data.pdf_url;

      if (!pdfUrl) {
        throw new Error('No PDF URL received');
      }

      const fullPdfUrl = `${apiUrl}${pdfUrl}`;

      const pdfResponse = await fetch(fullPdfUrl);

      if (!pdfResponse.ok) {
        throw new Error('Failed to download PDF');
      }

      const blob = await pdfResponse.blob();

      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `turgot_chat_${sessionId}.pdf`;
      document.body.appendChild(a);
      a.click();

      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (error) {
      console.error('Error exporting PDF:', error);
      alert("Une erreur est survenue lors de l'export du PDF. Veuillez réessayer.");
    } finally {
      setIsExporting(false);
    }
  };

  const handleReset = async () => {
    try {
      await clearSession();

      const newSessionId = crypto.randomUUID();
      localStorage.setItem('turgot_session_id', newSessionId);
      localStorage.setItem('turgot_last_activity', Date.now().toString());

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
    setMessages((prev) =>
      prev.map((message) => (message.id === messageId ? { ...message, feedback: value } : message))
    );
    try {
      await submitFeedback(messageId, value, targetMessage?.content.slice(0, 300) || '');
    } catch (error) {
      console.error('Error submitting feedback:', error);
    }
  };

  return (
    <main className="flex flex-col h-[100dvh]">
      <header className="shrink-0 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 transition-colors duration-200">
        <div className="max-w-4xl mx-auto px-3 sm:px-4 py-2 sm:py-3">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-3 min-w-0">
              <Image
                src="/turgot_v2.png"
                alt="Turgot Assistant"
                width={48}
                height={48}
                className="rounded-full shrink-0 w-10 h-10 sm:w-12 sm:h-12"
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
                <p className="text-xs sm:text-sm text-gray-600 dark:text-gray-300 truncate">{t('assistantTagline')}</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
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
        </div>
      </header>

      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-4xl mx-auto px-3 sm:px-4 py-2 sm:py-3">
            <ChatInterface messages={messages} isLoading={false} onFeedback={handleFeedback} />
          </div>
        </div>

        <SupportButton />

        <div className="shrink-0 bg-white dark:bg-gray-800 border-t border-gray-200 dark:border-gray-700 pb-safe transition-colors duration-200">
          <div className="max-w-4xl mx-auto px-3 sm:px-4 py-2">
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

      <DisclaimerModal isOpen={isDisclaimerOpen} onClose={() => setIsDisclaimerOpen(false)} />
    </main>
  );
}
