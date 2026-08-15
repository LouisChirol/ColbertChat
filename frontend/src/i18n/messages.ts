type Messages = {
  ui: Record<string, string>;
};

const FR_MESSAGES: Messages = {
  ui: {
    assistantTagline: "Assistant démarches & fiscalité (sources officielles)",
    openMenu: "Ouvrir le menu",
    chatPlaceholder: "Posez votre question...",
    sendMessage: "Envoyer le message",
    micStart: "Commencer la dictée vocale",
    micStop: "Arrêter l'enregistrement",
    resetTitle: "Réinitialiser la conversation",
    resetMessage:
      "Êtes-vous sûr de vouloir effacer toute l'historique de la conversation ? Cette action ne peut pas être annulée.",
    resetConfirm: "Réinitialiser",
    cancel: "Annuler",
  },
};

const EN_MESSAGES: Messages = {
  ui: {
    assistantTagline: "Public services & tax assistant (official sources)",
    openMenu: "Open menu",
    chatPlaceholder: "Ask your question...",
    sendMessage: "Send message",
    micStart: "Start voice dictation",
    micStop: "Stop recording",
    resetTitle: "Reset conversation",
    resetMessage:
      "Are you sure you want to clear the full conversation history? This cannot be undone.",
    resetConfirm: "Reset",
    cancel: "Cancel",
  },
};

export function getMessagesForLocale(locale: string): Messages {
  if (locale === "en") {
    return EN_MESSAGES;
  }

  return FR_MESSAGES;
}
