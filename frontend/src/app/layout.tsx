import Disclaimer from '@/components/Disclaimer'
import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import { headers } from 'next/headers'
import { NextIntlClientProvider } from 'next-intl'
import { getMessagesForLocale } from '@/i18n/messages'
import './globals.css'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'Turgot - Assistant Public Service',
  description: 'Votre assistant intelligent pour les services publics français',
  icons: {
    icon: '/turgot_avatar.png',
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const headerStore = headers()
  const acceptLanguage = headerStore.get('accept-language') || 'fr'
  const detectedLocale = acceptLanguage.split(',')[0]?.split('-')[0] || 'fr'
  const locale = ['fr', 'en', 'es', 'it', 'de', 'pt'].includes(detectedLocale)
    ? detectedLocale
    : 'fr'
  const messages = getMessagesForLocale(locale)

  return (
    <html lang={locale}>
      <body className={`${inter.className} bg-gray-50 dark:bg-gray-900 transition-colors duration-200`}>
        <NextIntlClientProvider locale={locale} messages={messages}>
          <Disclaimer />
          {children}
        </NextIntlClientProvider>
      </body>
    </html>
  )
} 