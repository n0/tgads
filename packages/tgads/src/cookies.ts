/**
 * Minimal cookie jar — enough for the Telegram Ads session, with zero deps.
 *
 * Supports loading a Netscape `cookies.txt` file (the format browsers/curl export),
 * building a `Cookie:` request header for a host, and capturing `Set-Cookie`
 * responses (e.g. the cookies set by the login flow).
 */
import { readFileSync } from "node:fs";

export interface Cookie {
  domain: string;
  /** true if the cookie applies to subdomains (leading-dot domains). */
  includeSubdomains: boolean;
  path: string;
  secure: boolean;
  /** unix seconds; 0/undefined = session cookie. */
  expires?: number;
  name: string;
  value: string;
}

export class CookieJar {
  private cookies: Cookie[] = [];

  /** Construct from an explicit list (rarely needed; prefer the static helpers). */
  constructor(cookies: Cookie[] = []) {
    for (const c of cookies) this.set(c);
  }

  /** Load a Netscape-format cookie file (tab- or whitespace-separated, `#` comments). */
  static fromFile(path: string): CookieJar {
    return CookieJar.fromNetscape(readFileSync(path, "utf8"));
  }

  /** Parse Netscape cookie-file text into a jar. */
  static fromNetscape(text: string): CookieJar {
    const jar = new CookieJar();
    for (const raw of text.split(/\r?\n/)) {
      const line = raw.trim();
      if (!line || line.startsWith("#")) continue;
      const parts = line.split("\t").length === 7 ? line.split("\t") : line.split(/\s+/);
      if (parts.length !== 7) continue;
      const [domain, flag, path, secure, expires, name, value] = parts as [
        string, string, string, string, string, string, string,
      ];
      jar.set({
        domain,
        includeSubdomains: flag.toUpperCase() === "TRUE" || domain.startsWith("."),
        path,
        secure: secure.toUpperCase() === "TRUE",
        expires: /^\d+$/.test(expires) ? Number(expires) : 0,
        name,
        value,
      });
    }
    return jar;
  }

  /** Insert/replace a cookie (keyed by domain+path+name). */
  set(c: Cookie): void {
    const i = this.cookies.findIndex(
      (x) => x.domain === c.domain && x.path === c.path && x.name === c.name,
    );
    if (i >= 0) this.cookies[i] = c;
    else this.cookies.push(c);
  }

  /** Read a cookie value by name (first match), regardless of domain. */
  get(name: string): string | undefined {
    return this.cookies.find((c) => c.name === name)?.value;
  }

  /** Build a `Cookie:` header value for the given URL. */
  header(url: string | URL): string {
    const u = typeof url === "string" ? new URL(url) : url;
    const host = u.hostname;
    return this.cookies
      .filter((c) => domainMatch(host, c.domain, c.includeSubdomains))
      .filter((c) => u.pathname.startsWith(c.path) || c.path === "/")
      .filter((c) => !c.secure || u.protocol === "https:")
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
  }

  /** Capture `Set-Cookie` response headers into the jar for the given URL host. */
  captureSetCookie(setCookieValues: string[], url: string | URL): void {
    const host = (typeof url === "string" ? new URL(url) : url).hostname;
    for (const sc of setCookieValues) {
      const [pair, ...attrs] = sc.split(";");
      const eq = pair?.indexOf("=") ?? -1;
      if (!pair || eq < 0) continue;
      const name = pair.slice(0, eq).trim();
      const value = pair.slice(eq + 1).trim();
      const attrMap = new Map(
        attrs.map((a) => {
          const i = a.indexOf("=");
          return i < 0
            ? [a.trim().toLowerCase(), ""]
            : [a.slice(0, i).trim().toLowerCase(), a.slice(i + 1).trim()];
        }),
      );
      const domain = (attrMap.get("domain") || host).replace(/^\./, "");
      this.set({
        domain: attrMap.has("domain") ? `.${domain}` : domain,
        includeSubdomains: attrMap.has("domain"),
        path: attrMap.get("path") || "/",
        secure: attrMap.has("secure"),
        expires: 0,
        name,
        value,
      });
    }
  }

  /** Serialize back to Netscape format (e.g. to persist refreshed login cookies). */
  toNetscape(): string {
    const head = "# Netscape HTTP Cookie File\n";
    return (
      head +
      this.cookies
        .map((c) =>
          [
            c.domain,
            c.includeSubdomains ? "TRUE" : "FALSE",
            c.path,
            c.secure ? "TRUE" : "FALSE",
            String(c.expires ?? 0),
            c.name,
            c.value,
          ].join("\t"),
        )
        .join("\n") + "\n"
    );
  }
}

function domainMatch(host: string, cookieDomain: string, includeSub: boolean): boolean {
  const cd = cookieDomain.replace(/^\./, "");
  if (host === cd) return true;
  return includeSub && host.endsWith(`.${cd}`);
}
