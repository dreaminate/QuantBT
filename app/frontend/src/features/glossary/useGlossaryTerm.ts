/**
 * v0.8.4 Day 3 · Glossary term 单条 fetch hook。
 *
 * 缓存：进程内 Map（页面刷新失效；够用，词条 fetch 频次低）
 * 失败：404 / network → 返 fallback 数据（不阻塞 UI）
 */

import { useEffect, useState } from "react";

export interface GlossaryTermFull {
  slug: string;
  frontmatter: {
    term: string;
    display: string;
    aliases: string[];
    level: "beginner" | "intermediate" | "advanced";
    category: string;
    formula_latex?: string | null;
    unit?: string | null;
    typical_range?: [number, number] | null;
    sources: string[];
    related: string[];
  };
  l1?: string;
  l2?: string;
  l3?: string;
  l4?: string;
  levels_available: string[];
}

export interface GlossaryFetchState {
  data: GlossaryTermFull | null;
  loading: boolean;
  error: string | null;
}

const _cache = new Map<string, GlossaryTermFull>();
const _inflight = new Map<string, Promise<GlossaryTermFull | null>>();

async function fetchGlossaryTerm(slug: string, level?: string): Promise<GlossaryTermFull | null> {
  const cacheKey = `${slug}::${level ?? "full"}`;
  if (_cache.has(cacheKey)) return _cache.get(cacheKey)!;
  if (_inflight.has(cacheKey)) return _inflight.get(cacheKey)!;

  const url = level
    ? `/api/glossary/${encodeURIComponent(slug)}?level=${level}`
    : `/api/glossary/${encodeURIComponent(slug)}`;
  const p = (async () => {
    try {
      const res = await fetch(url);
      if (!res.ok) return null;
      const json: GlossaryTermFull = await res.json();
      _cache.set(cacheKey, json);
      return json;
    } catch {
      return null;
    } finally {
      _inflight.delete(cacheKey);
    }
  })();
  _inflight.set(cacheKey, p);
  return p;
}

/**
 * 拉单个词条（按需 level 渐进披露）。slug 为 null 时不发请求。
 */
export function useGlossaryTerm(
  slug: string | null,
  level?: "l1" | "l2" | "l3" | "l4",
): GlossaryFetchState {
  const [state, setState] = useState<GlossaryFetchState>({
    data: null,
    loading: false,
    error: null,
  });

  useEffect(() => {
    if (!slug) {
      setState({ data: null, loading: false, error: null });
      return;
    }
    setState({ data: null, loading: true, error: null });
    let cancelled = false;
    fetchGlossaryTerm(slug, level).then((data) => {
      if (cancelled) return;
      if (data === null) {
        setState({ data: null, loading: false, error: "not_found" });
      } else {
        setState({ data, loading: false, error: null });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [slug, level]);

  return state;
}
