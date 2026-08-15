const SupportButton = () => (
  <div className="fixed bottom-2 right-3 z-30 sm:bottom-3 sm:right-4">
    <a
      href="https://coff.ee/louischirol"
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 transition-colors bg-white/70 dark:bg-gray-800/70 backdrop-blur-sm px-2 py-1 rounded-full shadow-sm border border-gray-200/80 dark:border-gray-700/80"
      style={{ pointerEvents: 'auto' }}
    >
      <span>🙏</span>
      <span className="hidden sm:inline">Soutenir</span>
    </a>
  </div>
);

export default SupportButton; 