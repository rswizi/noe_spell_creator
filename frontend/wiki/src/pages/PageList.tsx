import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchPages } from "../utils/api";

type PageSummary = {
  id: string;
  title: string;
  slug: string;
  updated_at: string;
};

const PageList: React.FC = () => {
  const [pages, setPages] = useState<PageSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    fetchPages()
      .then((payload) => {
        if (!active) {
          return;
        }
        setPages(payload.items);
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  return (
    <div>
      <header>
        <h1>Wiki Pages</h1>
        <p>Autosaved TipTap docs powered by the new wiki API.</p>
        <Link to="/new">
          <button>Create Page</button>
        </Link>
      </header>

      {loading ? (
        <p>Loading…</p>
      ) : (
        <table className="page-table">
          <thead>
            <tr>
              <th>Title</th>
              <th>Slug</th>
              <th>Updated</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {pages.map((page) => (
              <tr key={page.id}>
                <td>{page.title}</td>
                <td>{page.slug}</td>
                <td>{new Date(page.updated_at).toLocaleString()}</td>
                <td style={{ display: "flex", gap: "8px" }}>
                  <Link className="card-link" to={`/${page.id}`}>
                    View
                  </Link>
                  <Link className="card-link" to={`/${page.id}/edit`}>
                    Edit
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
};

export default PageList;
