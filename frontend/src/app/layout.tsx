import type { Metadata } from "next";
import Script from "next/script";
import localFont from "next/font/local";
import "./globals.css";

const inter = localFont({
  src: "../../node_modules/@fontsource-variable/inter/files/inter-latin-wght-normal.woff2",
  variable: "--font-inter",
  display: "swap",
  weight: "100 900",
});

const playfair = localFont({
  src: "../../node_modules/@fontsource-variable/playfair-display/files/playfair-display-latin-wght-normal.woff2",
  variable: "--font-serif",
  display: "swap",
  weight: "400 600",
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
      <body className={`${inter.variable} ${playfair.variable} font-sans antialiased`} style={{ paddingTop: "var(--atelier-nav-height, 0px)" }}>
        <Script src="https://atelierneyra.com/assets/native-nav/atelier-nav.js" data-project="geospatial-agent" strategy="afterInteractive" />
        {children}
      </body>
    </html>
  );
}
