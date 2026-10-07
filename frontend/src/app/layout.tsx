import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "YouTube AI Search & Chat",
  description: "Paste a YouTube URL, search the transcript, and chat with the video.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
