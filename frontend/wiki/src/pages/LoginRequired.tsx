import React from "react";

const LoginRequired: React.FC = () => {
  return (
    <div style={{ maxWidth: "680px", margin: "48px auto", padding: "0 16px" }}>
      <h1>Authentication Required</h1>
      <p>You need to sign in before accessing the wiki.</p>
      <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", marginTop: "14px" }}>
        <a href="/portal.html">
          <button>Go to Portal</button>
        </a>
        <a href="/my_account.html">
          <button>My Account</button>
        </a>
        <a href="/wiki">
          <button>Retry Wiki</button>
        </a>
      </div>
    </div>
  );
};

export default LoginRequired;
