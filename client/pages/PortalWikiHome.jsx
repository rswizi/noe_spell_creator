import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { listPages, categoriesTree, popularTags } from "../api/wiki";

export default function PortalWikiHome() {
  const [params, setParams] = useSearchParams();
  const [loading, setLoading] = useState(true);
  const [pages, setPages] = useState([]);
  const [cats, setCats] = useState([]);
  const [tags, setTags] = useState([]);
  const [error, setError] = useState(null);

  const q = params.get("q") || "";

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [pagesData, catsData, tagsData] = await Promise.all([
          listPages({ q, status: "published", limit: 20 }),
          categoriesTree(),
          popularTags(50),
        ]);
        if (!cancelled) {
          setPages(pagesData.items || pagesData || []);
          setCats(catsData.tree || catsData || []);
          setTags(tagsData.items || tagsData || []);
        }
      } catch (e) {
        if (!cancelled) setError(e.message || "Failed to load wiki");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [q]);

  function onSearch(e) {
    e.preventDefault();
    const v = new FormData(e.currentTarget).get("q")?.toString() ?? "";
    const next = new URLSearchParams(params);
    if (v) next.set("q", v); else next.delete("q");
    setParams(next, { replace: true });
  }

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6">
      <header className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-6">
        <h1 className="text-2xl md:text-3xl font-semibold">Wiki</h1>
        <form onSubmit={onSearch} className="flex gap-2 w-full md:w-auto">
          <input
            name="q"
            defaultValue={q}
            placeholder="Search pages…"
            className="flex-1 md:w-80 border rounded-lg px-3 py-2"
          />
          <button className="border rounded-lg px-4 py-2">Search</button>
        </form>
      </header>

      {error && <div className="bg-red-50 border border-red-200 text-red-700 rounded p-3 mb-4">{error}</div>}

      <div className="grid md:grid-cols-3 gap-6">
        {/* Left: categories + tags */}
        <aside className="md:col-span-1 space-y-6">
          <section>
            <h2 className="font-medium mb-2">Categories</h2>
            <CategoryTree nodes={cats} />
          </section>

          <section>
            <h2 className="font-medium mb-2">Popular tags</h2>
            <div className="flex flex-wrap gap-2">
              {tags.map((t) => (
                <Link
                  key={t.slug || t.name}
                  to={`/portal/wiki?q=${encodeURIComponent(t.name || t.slug)}`}
                  className="text-sm border rounded-full px-3 py-1"
                >
                  #{t.name || t.slug}
                </Link>
              ))}
            </div>
          </section>
        </aside>

        {/* Right: recent pages */}
        <main className="md:col-span-2">
          <h2 className="font-medium mb-3">{q ? `Results for “${q}”` : "Recent pages"}</h2>
          {loading ? (
            <div className="text-sm text-gray-500">Loading…</div>
          ) : (
            <ul className="space-y-3">
              {pages.map((p) => (
                <li key={p.slug} className="border rounded-lg p-3 hover:bg-gray-50">
                  <Link to={`/portal/wiki/${encodeURIComponent(p.slug)}`} className="font-medium">
                    {p.title}
                  </Link>
                  <div className="text-xs text-gray-500 mt-1">
                    {p.category_path?.join(" / ") || p.category?.name}
                    {p.tags?.length ? <> • {p.tags.map(t => t.name || t).join(", ")}</> : null}
                  </div>
                  {p.excerpt && <p className="text-sm mt-2 line-clamp-3">{p.excerpt}</p>}
                </li>
              ))}
              {!pages.length && <li className="text-sm text-gray-500">No pages found.</li>}
            </ul>
          )}
        </main>
      </div>
    </div>
  );
}

function CategoryTree({ nodes = [], level = 0 }) {
  if (!nodes?.length) return <p className="text-sm text-gray-500">No categories.</p>;
  return (
    <ul className={level === 0 ? "space-y-1" : "ml-4 space-y-1"}>
      {nodes.map((n) => (
        <li key={n.slug || n.name}>
          <Link to={`/portal/wiki?q=${encodeURIComponent(`category:${n.slug || n.name}`)}`} className="hover:underline">
            {n.name}
          </Link>
          {n.children?.length ? <CategoryTree nodes={n.children} level={level + 1} /> : null}
        </li>
      ))}
    </ul>
  );
}