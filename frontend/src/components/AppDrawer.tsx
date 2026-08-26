import { getLastUpdate } from '@/services/api';
import { Dialog, Transition } from '@headlessui/react';
import { DocumentArrowDownIcon, HeartIcon, HomeIcon, TrashIcon, XMarkIcon } from '@heroicons/react/24/outline';
import { Github } from 'lucide-react';
import { Fragment, useEffect, useState } from 'react';

interface AppDrawerProps {
  open: boolean;
  onClose: () => void;
  onExportPDF: () => void;
  onClear: () => void;
  onSupport: () => void;
  onGitHub: () => void;
  isExporting: boolean;
  isClearing: boolean;
  disableExport: boolean;
  disableClear: boolean;
}

const AppDrawer = ({
  open,
  onClose,
  onExportPDF,
  onClear,
  onSupport,
  onGitHub,
  isExporting,
  isClearing,
  disableExport,
  disableClear,
}: AppDrawerProps) => {
  const [lastUpdate, setLastUpdate] = useState<string>('');

  useEffect(() => {
    const fetchLastUpdate = async () => {
      try {
        const date = await getLastUpdate();
        setLastUpdate(date);
      } catch (error) {
        console.error('Error fetching last update:', error);
      }
    };

    if (open) {
      fetchLastUpdate();
    }
  }, [open]);

  return (
    <Transition.Root show={open} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={onClose}>
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-300"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-200"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <div className="fixed inset-0 bg-black bg-opacity-30 transition-opacity" />
        </Transition.Child>

        <div className="fixed inset-0 overflow-hidden">
          <div className="absolute inset-0 overflow-hidden">
            <div className="pointer-events-none fixed inset-y-0 left-0 flex max-w-full pr-10">
              <Transition.Child
                as={Fragment}
                enter="transform transition ease-in-out duration-300"
                enterFrom="-translate-x-full"
                enterTo="translate-x-0"
                leave="transform transition ease-in-out duration-200"
                leaveFrom="translate-x-0"
                leaveTo="-translate-x-full"
              >
                <Dialog.Panel className="pointer-events-auto w-72 max-w-full bg-white dark:bg-gray-900 h-full shadow-xl flex flex-col">
                  <div className="flex items-center justify-between px-4 py-4 border-b border-gray-200 dark:border-gray-700">
                    <h2 className="text-lg font-bold text-gray-900 dark:text-white">Menu</h2>
                    <button onClick={onClose} className="p-2 rounded hover:bg-gray-100 dark:hover:bg-gray-800">
                      <XMarkIcon className="h-6 w-6 text-gray-700 dark:text-gray-200" />
                    </button>
                  </div>
                  <div className="flex-1 overflow-y-auto">
                    <nav className="flex-1 flex flex-col gap-2 p-4">
                      <a
                        href="https://louischirol.fr"
                        className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-gray-50 dark:bg-gray-800 text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                      >
                        <HomeIcon className="h-5 w-5 shrink-0" />
                        <span>louischirol.fr</span>
                      </a>
                      <button
                        onClick={onExportPDF}
                        disabled={isExporting || disableExport}
                        className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                          isExporting || disableExport
                            ? 'bg-gray-100 dark:bg-gray-700 text-gray-400 dark:text-gray-500 cursor-not-allowed'
                            : 'bg-blue-50 dark:bg-blue-900/50 text-blue-600 dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-blue-900'
                        }`}
                      >
                        <DocumentArrowDownIcon className="h-5 w-5" />
                        <span>Exporter en PDF</span>
                      </button>
                      <button
                        onClick={onClear}
                        disabled={isClearing || disableClear}
                        className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                          isClearing || disableClear
                            ? 'bg-gray-100 dark:bg-gray-700 text-gray-400 dark:text-gray-500 cursor-not-allowed'
                            : 'bg-red-50 dark:bg-red-900/50 text-red-600 dark:text-red-300 hover:bg-red-100 dark:hover:bg-red-900'
                        }`}
                      >
                        <TrashIcon className="h-5 w-5" />
                        <span>Vider la discussion</span>
                      </button>
                      <button
                        onClick={onSupport}
                        className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-yellow-50 dark:bg-yellow-900/50 text-yellow-700 dark:text-yellow-300 hover:bg-yellow-100 dark:hover:bg-yellow-900 transition-colors"
                      >
                        <HeartIcon className="h-5 w-5" />
                        <span>Soutenir le projet</span>
                      </button>
                      <button
                        onClick={onGitHub}
                        className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-gray-50 dark:bg-gray-800 text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                      >
                        <Github className="h-5 w-5" />
                        <span>GitHub</span>
                      </button>
                    </nav>
                  </div>

                  {lastUpdate && (
                    <div className="px-4 py-3 border-t border-gray-200 dark:border-gray-700">
                      <p className="text-sm text-gray-500 dark:text-gray-400 italic">
                        Base de données mise à jour le {lastUpdate}
                      </p>
                    </div>
                  )}
                </Dialog.Panel>
              </Transition.Child>
            </div>
          </div>
        </div>
      </Dialog>
    </Transition.Root>
  );
};

export default AppDrawer; 