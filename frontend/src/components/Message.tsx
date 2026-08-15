'use client';

import Image from 'next/image';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import DataSourceIndicator from './DataSourceIndicator';

interface Source {
  url: string;
  title: string;
  excerpt: string;
  data_source?: string;
}

interface MessageProps {
  messageId: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: Source[];
  secondarySources?: Source[];
  isError?: boolean;
  isStreaming?: boolean;
  feedback?: 1 | -1 | null;
  onFeedback?: (messageId: string, value: 1 | -1) => void;
}

const Message = ({
  messageId,
  role,
  content,
  sources = [],
  secondarySources = [],
  isError = false,
  isStreaming = false,
  feedback = null,
  onFeedback,
}: MessageProps) => {
  const isUser = role === 'user';

  const getAvatarSrc = () => {
    if (isStreaming) {
      return '/turgot_thinking.png';
    }
    if (isError || content.includes("Désolé, une erreur est survenue. Veuillez réessayer.")) {
      return '/turgot_sorry.png';
    }
    return '/turgot_avatar.png';
  };

  // Helper function to categorize sources by type with deduplication
  const categorizeSources = (sources: Source[]) => {
    // First, identify all sources by their base URL (without query parameters)
    const sourceMap = new Map<string, Source>();
    
    sources.forEach(source => {
      const baseUrl = source.url.split('?')[0]; // Remove query parameters for comparison
      
      // If this URL is already in the map, prioritize entreprendre over vosdroits
      if (sourceMap.has(baseUrl)) {
        const existingSource = sourceMap.get(baseUrl)!;
        const existingIsEntreprendre = existingSource.url.includes('entreprendre');
        const currentIsEntreprendre = source.url.includes('entreprendre');
        
        // Keep the entreprendre version if either is entreprendre
        if (currentIsEntreprendre && !existingIsEntreprendre) {
          sourceMap.set(baseUrl, source);
        }
      } else {
        sourceMap.set(baseUrl, source);
      }
    });
    
    // Now categorize the deduplicated sources
    const deduplicatedSources = Array.from(sourceMap.values());
    const entreprendreSources = deduplicatedSources.filter(s => s.url.includes('entreprendre'));
    const vosdroitsSources = deduplicatedSources.filter(s => s.url.includes('vosdroits') && !s.url.includes('entreprendre'));
    const otherSources = deduplicatedSources.filter(s => !s.url.includes('vosdroits') && !s.url.includes('entreprendre'));
    
    // After deduplication, show both types of sources
    // The deduplication already removed duplicates, so we can show both
    return { 
      vosdroitsSources, 
      entreprendreSources, 
      otherSources 
    };
  };

  // Extract sources from markdown content if they're embedded in the response
  const extractSourcesFromContent = (content: string) => {
    const sourceMatches = content.match(/\[([^\]]+)\]\(([^)]+)\)/g);
    if (sourceMatches) {
      return sourceMatches.map(match => {
        const [, title, url] = match.match(/\[([^\]]+)\]\(([^)]+)\)/) || [];
        return { url, title: title || url, excerpt: '' };
      });
    }
    return [];
  };

  // Get all sources (from props and embedded in content)
  const allSources = [...sources, ...extractSourcesFromContent(content)];
  const { vosdroitsSources, entreprendreSources, otherSources } = categorizeSources(allSources);

  const getSourceTypeLabel = (source: Source) => {
    if (source.url.includes('vosdroits') || source.data_source === 'vosdroits') return 'Particuliers';
    if (source.url.includes('entreprendre') || source.data_source === 'entreprendre') return 'Professionnels';
    return 'Officiel';
  };

  const getSourceHost = (url: string) => {
    try {
      return new URL(url).hostname;
    } catch {
      return url;
    }
  };

  return (
    <article className={`flex ${isUser ? 'justify-end' : 'justify-start'} gap-3`} aria-live={!isUser && isStreaming ? 'polite' : undefined}>
      {!isUser && (
        <div className="w-12 h-12 rounded-full overflow-hidden flex-shrink-0">
          <Image
            src={getAvatarSrc()}
            alt="Turgot Assistant"
            width={48}
            height={48}
            className="w-full h-full object-cover"
          />
        </div>
      )}
      <div
        className={`max-w-[80%] rounded-lg p-4 break-words focus-within:ring-2 focus-within:ring-blue-500 ${
          isUser
            ? 'bg-blue-500 text-white dark:bg-blue-600'
            : isError || content.includes("Désolé, une erreur est survenue. Veuillez réessayer.")
            ? 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
            : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200'
        } transition-colors duration-200`}
      >
        {/* Data Source Indicators for Assistant Messages */}
        {!isUser && allSources.length > 0 && (
          <div className="mb-3">
            <DataSourceIndicator sources={allSources} />
          </div>
        )}

        <div className={`prose prose-sm max-w-none ${isUser ? 'prose-invert' : 'prose-gray dark:prose-invert'}`}>
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              // Style links
              a: ({ node, ...props }) => (
                <a
                  {...props}
                  className={`break-all ${
                    isUser
                      ? 'text-blue-200 hover:text-white'
                      : 'text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300'
                  } underline transition-colors`}
                  target="_blank"
                  rel="noopener noreferrer"
                />
              ),
              // Style lists
              ul: ({ node, ...props }) => (
                <ul {...props} className={`list-disc pl-4 space-y-1 ${isUser ? 'text-white' : 'text-gray-800 dark:text-gray-200'}`} />
              ),
              ol: ({ node, ...props }) => (
                <ol {...props} className={`list-decimal pl-4 space-y-1 ${isUser ? 'text-white' : 'text-gray-800 dark:text-gray-200'}`} />
              ),
              // Style paragraphs
              p: ({ node, ...props }) => (
                <p {...props} className={`mb-2 ${isUser ? 'text-white' : 'text-gray-800 dark:text-gray-200'}`} />
              ),
              // Style headings
              h1: ({ node, ...props }) => (
                <h1 {...props} className={`text-xl font-bold mb-2 ${isUser ? 'text-white' : 'text-gray-900 dark:text-gray-100'}`} />
              ),
              h2: ({ node, ...props }) => (
                <h2 {...props} className={`text-lg font-bold mb-2 ${isUser ? 'text-white' : 'text-gray-900 dark:text-gray-100'}`} />
              ),
              h3: ({ node, ...props }) => (
                <h3 {...props} className={`text-base font-bold mb-2 ${isUser ? 'text-white' : 'text-gray-900 dark:text-gray-100'}`} />
              ),
              // Style code blocks
              code: ({ node, inline, ...props }: { node?: any; inline?: boolean } & React.HTMLAttributes<HTMLElement>) => (
                inline ? (
                  <code {...props} className={`${isUser ? 'bg-blue-600 text-white' : 'bg-gray-200 text-gray-800 dark:bg-gray-600 dark:text-gray-200'} rounded px-1 py-0.5`} />
                ) : (
                  <code {...props} className={`block ${isUser ? 'bg-blue-600 text-white' : 'bg-gray-200 text-gray-800 dark:bg-gray-600 dark:text-gray-200'} rounded p-2 my-2`} />
                )
              ),
            }}
          >
            {content}
          </ReactMarkdown>
        </div>
        
        {/* Enhanced Sources Display */}
        {(vosdroitsSources.length > 0 || entreprendreSources.length > 0 || otherSources.length > 0 || secondarySources.length > 0) && (
          <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-600">
            <details className="group">
              <summary className="flex items-center gap-2 cursor-pointer text-sm font-semibold text-gray-900 dark:text-gray-100 hover:text-blue-700 dark:hover:text-blue-300 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded">
                <svg
                  className="w-4 h-4 transform group-open:rotate-90 transition-transform"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
                Sources ({vosdroitsSources.length + entreprendreSources.length + otherSources.length + secondarySources.length})
              </summary>
              
              <div className="mt-3 space-y-3 pl-1">
                {[...vosdroitsSources, ...entreprendreSources, ...otherSources, ...secondarySources].map((source, index) => (
                  <div
                    key={`${source.url}-${index}`}
                    className="rounded-md border border-gray-200 dark:border-gray-500 bg-white/70 dark:bg-gray-800/70 p-3"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate">
                        {source.title || source.url}
                      </p>
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-200">
                        {getSourceTypeLabel(source)}
                      </span>
                    </div>
                    <p className="text-xs text-gray-600 dark:text-gray-300 mt-1">
                      {getSourceHost(source.url)}
                    </p>
                    {source.excerpt && (
                      <p className="text-xs text-gray-700 dark:text-gray-300 mt-2 line-clamp-3">
                        {source.excerpt}
                      </p>
                    )}
                    <a
                      href={source.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex mt-2 text-xs font-medium text-blue-700 dark:text-blue-300 hover:underline"
                    >
                      Ouvrir la source
                    </a>
                  </div>
                ))}
              </div>
            </details>
          </div>
        )}

        {!isUser && !isStreaming && !isError && (
          <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-600">
            <p className="text-xs text-gray-700 dark:text-gray-300 mb-2">Cette réponse vous a-t-elle aidé ?</p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => onFeedback && onFeedback(messageId, 1)}
                aria-label="Réponse utile"
                aria-pressed={feedback === 1}
                className={`px-3 py-1.5 rounded-md text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                  feedback === 1
                    ? 'bg-green-600 text-white'
                    : 'bg-gray-200 text-gray-800 hover:bg-gray-300 dark:bg-gray-600 dark:text-gray-100 dark:hover:bg-gray-500'
                }`}
              >
                👍 Utile
              </button>
              <button
                type="button"
                onClick={() => onFeedback && onFeedback(messageId, -1)}
                aria-label="Réponse non utile"
                aria-pressed={feedback === -1}
                className={`px-3 py-1.5 rounded-md text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                  feedback === -1
                    ? 'bg-red-600 text-white'
                    : 'bg-gray-200 text-gray-800 hover:bg-gray-300 dark:bg-gray-600 dark:text-gray-100 dark:hover:bg-gray-500'
                }`}
              >
                👎 À améliorer
              </button>
            </div>
          </div>
        )}
      </div>
    </article>
  );
};

export default Message; 