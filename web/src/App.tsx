import { useEffect, useState } from "react";
import { ApiError, exchange, getMe, session } from "./api";
import { Dashboard } from "./Dashboard";
import type { Me } from "./types";

type Phase =
  | { name: "loading" }
  | { name: "needLogin"; reason: string }
  | { name: "notManager"; me: Me }
  | { name: "ready"; me: Me };

export default function App() {
  const [phase, setPhase] = useState<Phase>({ name: "loading" });

  useEffect(() => {
    void bootstrap(setPhase);
  }, []);

  switch (phase.name) {
    case "loading":
      return <Splash>Carregando…</Splash>;
    case "needLogin":
      return <LoginNeeded reason={phase.reason} />;
    case "notManager":
      return <NotManager me={phase.me} />;
    case "ready":
      return <Dashboard me={phase.me} onSignedOut={() => setPhase({ name: "needLogin", reason: "" })} />;
  }
}

async function bootstrap(setPhase: (p: Phase) => void) {
  // 1) Veio do magic-link? Troca o token e limpa a URL.
  const url = new URL(window.location.href);
  const loginToken = url.searchParams.get("token");
  if (loginToken) {
    try {
      await exchange(loginToken);
    } catch {
      setPhase({
        name: "needLogin",
        reason: "Esse link de acesso é inválido ou expirou. Envie /login no bot para gerar outro.",
      });
      return;
    } finally {
      url.searchParams.delete("token");
      window.history.replaceState({}, "", url.pathname + url.search);
    }
  }

  // 2) Tem sessão guardada? Resolve o usuário.
  if (!session.get()) {
    setPhase({ name: "needLogin", reason: "" });
    return;
  }
  try {
    const me = await getMe();
    setPhase(me.is_admin ? { name: "ready", me } : { name: "notManager", me });
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      session.clear();
      setPhase({ name: "needLogin", reason: "Sua sessão expirou. Envie /login no bot para entrar de novo." });
    } else {
      setPhase({ name: "needLogin", reason: "Não consegui falar com o servidor. Tente novamente." });
    }
  }
}

function Splash({ children }: { children: React.ReactNode }) {
  return (
    <div className="splash">
      <Wordmark />
      <p className="muted">{children}</p>
    </div>
  );
}

function LoginNeeded({ reason }: { reason: string }) {
  return (
    <div className="splash">
      <Wordmark />
      <div className="gate">
        <h1>Acesse pelo bot</h1>
        <p>
          Envie <code>/login</code> para o Pedro Finanças no Telegram. Ele te manda um link de
          acesso — abra aqui no navegador.
        </p>
        {reason && <p className="gate-note">{reason}</p>}
      </div>
    </div>
  );
}

function NotManager({ me }: { me: Me }) {
  return (
    <div className="splash">
      <Wordmark />
      <div className="gate">
        <h1>Painel dos gestores</h1>
        <p>
          Olá, {me.display_name}. Os relatórios são de admins/owners da empresa. Você continua
          lançando e acompanhando gastos pelo bot.
        </p>
        <button
          className="btn-ghost"
          onClick={() => {
            session.clear();
            window.location.reload();
          }}
        >
          Sair
        </button>
      </div>
    </div>
  );
}

export function Wordmark() {
  return (
    <div className="wordmark">
      <span className="wordmark-mark">R$</span>
      <span className="wordmark-name">Pedro Finanças</span>
    </div>
  );
}
