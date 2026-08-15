import { getRequestConfig } from "next-intl/server";
import { getMessagesForLocale } from "./messages";

const SUPPORTED_LOCALES = new Set(["fr", "en", "es", "it", "de", "pt"]);

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = (await requestLocale) || "fr";
  const locale = SUPPORTED_LOCALES.has(requested) ? requested : "fr";

  return {
    locale,
    messages: getMessagesForLocale(locale),
  };
});
