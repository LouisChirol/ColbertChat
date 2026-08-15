type Messages = {
  ui: Record<string, string>;
};

const FR_MESSAGES: Messages = {
  ui: {
    assistantTagline: "Votre assistant administratif",
    openMenu: "Ouvrir le menu",
    uploadConsentWarning:
      "Ne téléversez pas de données sensibles sans consentement explicite. Les documents sont validés en mémoire uniquement.",
    uploadButton: "Téléverser un PDF",
    chatPlaceholder: "Posez votre question...",
    sendMessage: "Envoyer le message",
    micStart: "Commencer la dictée vocale",
    micStop: "Arrêter l'enregistrement",
    resetTitle: "Réinitialiser la conversation",
    resetMessage:
      "Êtes-vous sûr de vouloir effacer toute l'historique de la conversation ? Cette action ne peut pas être annulée.",
    resetConfirm: "Réinitialiser",
    cancel: "Annuler",
    consentTitle: "Consentement de téléversement",
    consentMessage:
      "Vous confirmez comprendre que le document pourra être traité par un modèle d'IA et qu'il ne doit pas contenir de données personnelles sensibles.",
    consentConfirm: "J'accepte et je continue",
  },
};

const EN_MESSAGES: Messages = {
  ui: {
    assistantTagline: "Your public-services assistant",
    openMenu: "Open menu",
    uploadConsentWarning:
      "Do not upload sensitive data without explicit consent. Documents are validated in-memory only.",
    uploadButton: "Upload PDF",
    chatPlaceholder: "Ask your question...",
    sendMessage: "Send message",
    micStart: "Start voice dictation",
    micStop: "Stop recording",
    resetTitle: "Reset conversation",
    resetMessage:
      "Are you sure you want to clear the full conversation history? This cannot be undone.",
    resetConfirm: "Reset",
    cancel: "Cancel",
    consentTitle: "Upload consent",
    consentMessage:
      "You confirm that the document may be processed by an AI model and should not include sensitive personal data.",
    consentConfirm: "I agree and continue",
  },
};

export function getMessagesForLocale(locale: string): Messages {
  if (locale === "en") {
    return EN_MESSAGES;
  }

  return FR_MESSAGES;
}
