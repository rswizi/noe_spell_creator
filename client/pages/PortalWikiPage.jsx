import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getPage } from "../api/wiki";

export default function PortalWikiPage() {
  const { slug } = useParams();
  const [page, setPage] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getPage(slug)
      .then((data) => { if (!cancelled) setPage(data); })
      .catch((e) => { if (!cancelled) setError(e.message || "Failed to load page"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [slug]);

  if (loading) return <div className="max-w-3xl mx-auto p-4">Loading…</div>;
  if (error)   return <div className="max-w-3xl mx-auto p-4 text-red-600">{error}</div>;
  if (!page)   return <div className="max-w-3xl mx-auto p-4">Not found.</div>;

  return (
    <article className="max-w-3xl mx-auto p-4 md:p-6">
      <div className="text-sm mb-3">
        <Link to="/portal/wiki" className="underline">Wiki Home</Link>
        {page.category_path?.length ? (
          <> / {page.category_path.map((c, i) => (
            <span key={i} className="text-gray-600">{c}{i < page.category_path.length - 1 ? " / " : ""}</span>
          ))}</>
        ) : null}
      </div>

      <h1 className="text-3xl font-semibold mb-2">{page.title}</h1>

      {page.updated_at || page.created_at ? (
        <div className="text-xs text-gray-500 mb-4">
          {page.updated_at ? `Updated ${new Date(page.updated_at).toLocaleString()}` :
           page.created_at ? `Created ${new Date(page.created_at).toLocaleString()}` : null}
        </div>
      ) : null}

      {/* Render rich HTML produced by your editor (server should sanitize) */}
      <div className="prose prose-sm md:prose-base max-w-none" dangerouslySetInnerHTML={{ __html: page.html || "" }} />

      {page.images?.length ? (
        <div className="mt-6 grid grid-cols-2 md:grid-cols-3 gap-3">
          {page.images.map((src, i) => (
            <img key={i} src={src} alt="" className="w-full rounded-lg border" />
          ))}
        </div>
      ) : null}

      {page.tags?.length ? (
        <div className="mt-6 flex flex-wrap gap-2">
          {page.tags.map((t) => (
            <Link key={t.slug || t} to={`/portal/wiki?q=${encodeURIComponent(t.name || t.slug || t)}`}
              className="text-xs border rounded-full px-2 py-1">#{t.name || t.slug || t}</Link>
          ))}
        </div>
      ) : null}
    </article>
  );
}