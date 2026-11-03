import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import type { ChatMessage, ChatThread, VerdictResponse } from '../lib/api';
import {
  createChatThread,
  listChatMessages,
  listChatThreads,
  sendChatMessage,
} from '../lib/api';

const DISCLAIMER = 'General guidance, not financial advice.';

function engineLabel(engine: ChatMessage['engine']): string {
  if (engine === 'rule-based') return 'Engine: rule-based';
  if (engine === 'ollama') return 'Engine: ollama (local model)';
  if (typeof engine === 'string' && engine.trim() !== '') return `Engine: ${engine}`;
  return 'Engine: not stated by server';
}

interface ChatPanelProps {
  /** A check the user asked to discuss; a thread is created once. */
  pendingCheck: VerdictResponse | null;
  onPendingConsumed: () => void;
}

/**
 * Chat threads about checks. Every assistant message shows its engine
 * label and the guidance disclaimer; rule-based replies are labelled
 * rule-based and never presented as LLM output.
 */
export default function ChatPanel({ pendingCheck, onPendingConsumed }: ChatPanelProps) {
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingThreads, setLoadingThreads] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState('');
  const pendingConsumedRef = useRef<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoadingThreads(true);
    void listChatThreads()
      .then((result) => {
        if (!cancelled) setThreads(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Could not load chat threads.');
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingThreads(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // "Discuss this check": create exactly one thread linked to the check.
  useEffect(() => {
    if (!pendingCheck) return;
    const key = String(pendingCheck.id);
    if (pendingConsumedRef.current === key) {
      onPendingConsumed();
      return;
    }
    pendingConsumedRef.current = key;
    setCreating(true);
    setError(null);
    void createChatThread({ check_id: pendingCheck.id })
      .then((thread) => {
        setThreads((previous) => [thread, ...previous]);
        setSelectedId(String(thread.id));
        setMessages([]);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Could not start a chat about this check.');
      })
      .finally(() => {
        setCreating(false);
        onPendingConsumed();
      });
    // onPendingConsumed is stable (App setState wrapper); run once per check.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingCheck]);

  async function loadMessages(threadId: string) {
    setLoadingMessages(true);
    setSendError(null);
    try {
      setMessages(await listChatMessages(threadId));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load messages.');
    } finally {
      setLoadingMessages(false);
    }
  }

  function selectThread(thread: ChatThread) {
    setSelectedId(String(thread.id));
    setError(null);
    void loadMessages(String(thread.id));
  }

  async function handleNewThread() {
    setCreating(true);
    setError(null);
    try {
      const thread = await createChatThread({});
      setThreads((previous) => [thread, ...previous]);
      setSelectedId(String(thread.id));
      setMessages([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start a new chat.');
    } finally {
      setCreating(false);
    }
  }

  async function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedId || sending) return;
    const content = draft.trim();
    if (!content) return;
    setDraft('');
    setSending(true);
    setSendError(null);
    const userMessage: ChatMessage = {
      id: `local-${Date.now()}`,
      role: 'user',
      content,
      engine: null,
      created_at: new Date().toISOString(),
    };
    setMessages((previous) => [...previous, userMessage]);
    try {
      const reply = await sendChatMessage(selectedId, content);
      // The contract returns the assistant message; tolerate a
      // differently-shaped reply by reloading the thread instead.
      if (reply && typeof reply === 'object' && typeof reply.content === 'string') {
        setMessages((previous) => [...previous, reply]);
      } else {
        await loadMessages(selectedId);
      }
    } catch (err) {
      setSendError(err instanceof Error ? err.message : 'Message failed to send.');
    } finally {
      setSending(false);
    }
  }

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ block: 'end' });
  }, [messages]);

  const selectedThread = threads.find((thread) => String(thread.id) === selectedId) ?? null;

  return (
    <div>
      <h2 className="text-[22px] font-bold leading-snug text-[var(--text-primary)]">Chat</h2>
      <p className="mt-1 text-sm leading-relaxed text-[var(--text-secondary)]">
        Ask follow-up questions about a check. Replies are general guidance,
        not financial advice, and every assistant reply names its engine.
      </p>

      {error ? (
        <p role="alert" className="mt-4 rounded-lg border border-red-500/40 bg-red-500/15 px-3 py-2.5 text-sm text-red-400">
          {error}
        </p>
      ) : null}

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-[280px_1fr]">
        <section
          aria-label="Chat threads"
          className="rounded-2xl border border-[var(--border)] bg-[var(--surface-card)] p-4"
        >
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-[var(--text-primary)]">Threads</h3>
            <button
              type="button"
              onClick={() => void handleNewThread()}
              disabled={creating}
              className="min-h-11 rounded-lg bg-emerald-500 px-3 py-2 text-sm font-bold text-stone-950 hover:bg-emerald-600 disabled:opacity-50"
            >
              {creating ? 'Starting…' : 'New chat'}
            </button>
          </div>
          {loadingThreads ? (
            <p className="mt-3 text-sm text-[var(--text-secondary)]">Loading threads…</p>
          ) : threads.length === 0 ? (
            <p className="mt-3 text-sm leading-relaxed text-[var(--text-secondary)]">
              No chats yet. Start a new chat, or use “Discuss this check” on a
              verdict to chat about that check.
            </p>
          ) : (
            <ul className="mt-3 space-y-2">
              {threads.map((thread) => (
                <li key={String(thread.id)}>
                  <button
                    type="button"
                    onClick={() => selectThread(thread)}
                    aria-current={selectedId === String(thread.id) ? 'true' : undefined}
                    className={[
                      'min-h-11 w-full rounded-lg px-3 py-2 text-left text-sm',
                      selectedId === String(thread.id)
                        ? 'bg-emerald-500/15 font-semibold text-emerald-400'
                        : 'text-[var(--text-primary)] hover:bg-[var(--surface-secondary)]',
                    ].join(' ')}
                  >
                    <span className="block">
                      {thread.title
                        ? thread.title
                        : thread.check_id
                          ? `Check ${String(thread.check_id)}`
                          : 'General chat'}
                    </span>
                    <span className="block font-mono text-xs text-[var(--text-muted)]">
                      {new Date(thread.created_at).toLocaleString()}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section
          aria-label="Messages"
          className="flex min-h-[420px] flex-col rounded-2xl border border-[var(--border)] bg-[var(--surface-card)] p-4"
        >
          {!selectedThread ? (
            <p className="text-sm leading-relaxed text-[var(--text-secondary)]">
              Select a thread, or start a new chat.
            </p>
          ) : (
            <>
              <h3 className="text-lg font-semibold text-[var(--text-primary)]">
                {selectedThread.check_id
                  ? `Discussing check ${String(selectedThread.check_id)}`
                  : 'General chat'}
              </h3>
              {loadingMessages ? (
                <p className="mt-3 text-sm text-[var(--text-secondary)]">Loading messages…</p>
              ) : messages.length === 0 ? (
                <p className="mt-3 text-sm text-[var(--text-secondary)]">
                  No messages yet. Ask your first question below.
                </p>
              ) : (
                <ul className="mt-3 flex-1 space-y-3">
                  {messages.map((message) => (
                    <li
                      key={String(message.id)}
                      className={
                        message.role === 'user'
                          ? 'ml-auto max-w-[85%] rounded-lg bg-emerald-500/15 px-3 py-2.5 text-sm leading-relaxed text-[var(--text-primary)]'
                          : 'max-w-[85%] rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] px-3 py-2.5 text-sm leading-relaxed text-[var(--text-primary)]'
                      }
                    >
                      <p className="text-[11px] font-bold tracking-wide text-[var(--text-muted)] uppercase">
                        {message.role === 'user' ? 'You' : 'Assistant'}
                      </p>
                      <p className="mt-1 whitespace-pre-wrap">{message.content}</p>
                      {message.role === 'assistant' ? (
                        <p className="mt-2 font-mono text-xs text-[var(--text-secondary)]">
                          {engineLabel(message.engine)}
                        </p>
                      ) : null}
                      {message.role === 'assistant' ? (
                        <p className="mt-1 text-xs text-[var(--text-secondary)]">{DISCLAIMER}</p>
                      ) : null}
                    </li>
                  ))}
                  <div ref={messagesEndRef} />
                </ul>
              )}
              {sendError ? (
                <p role="alert" className="mt-3 text-sm text-red-400">
                  {sendError}
                </p>
              ) : null}
              <form onSubmit={handleSend} className="mt-4 flex flex-col gap-2 sm:flex-row">
                <label className="sr-only" htmlFor="chat-input">
                  Message
                </label>
                <input
                  id="chat-input"
                  type="text"
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  disabled={sending}
                  placeholder="Ask about this check…"
                  className="min-h-11 flex-1 rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] px-3 py-2 text-base text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/50 focus:outline-none disabled:opacity-50"
                />
                <button
                  type="submit"
                  disabled={sending || draft.trim() === ''}
                  className="min-h-11 rounded-lg bg-emerald-500 px-4 py-2.5 text-base font-bold text-stone-950 hover:bg-emerald-600 disabled:opacity-50"
                >
                  {sending ? 'Sending…' : 'Send'}
                </button>
              </form>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
