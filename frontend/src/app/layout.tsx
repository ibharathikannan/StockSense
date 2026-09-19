import type { Metadata } from "next";
import "./globals.css";
import { LoadingOverlay } from "@/components/LoadingOverlay";
import { AuthProvider } from "@/lib/auth";
import { APP_NAME } from "@/lib/config";

export const metadata: Metadata = {
  title: { default: APP_NAME, template: `%s · ${APP_NAME}` },
  description: "StockSense — explainable stock research for beginner investors",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">
        <LoadingOverlay />
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
