import type { Metadata } from "next";
import Script from "next/script";
import { Inter, Playfair_Display } from "next/font/google";
import "./globals.css";

const inter = Inter({ 
  subsets: ["latin"],
  variable: "--font-inter",
});

const playfair = Playfair_Display({
  subsets: ["latin"],
  variable: "--font-serif",
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "Leo - Agentic Maps",
  description: "AI-powered geospatial intelligence platform. Analyze locations, markets, supply chains, and risks with natural language.",
  keywords: ["maps", "AI", "geospatial", "intelligence", "analysis", "Gemini"],
  authors: [{ name: "Leo" }],
  openGraph: {
    title: "Leo - Agentic Maps",
    description: "AI-powered geospatial intelligence platform",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.variable} ${playfair.variable} font-sans antialiased`}>
        <Script src="https://atelierneyra.com/assets/native-nav/atelier-nav.js" data-project="geospatial-agent" strategy="afterInteractive" />
        {children}
      </body>
    </html>
  );
}
