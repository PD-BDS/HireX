import React, { useState, useEffect, useRef } from 'react';
import { User, Bot, Send, Menu, Loader2, MessageSquare, Briefcase, Search, ArrowRight } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import clsx from 'clsx';
import { Sidebar } from '../Sidebar';
import { sendMessage, type ChatMessage, listSessions, createSession, deleteSession, getSession } from '../../api/client';

export const ChatInterface: React.FC = () => {
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [sessionId, setSessionId] = useState<string | null>(null);
    const [sessions, setSessions] = useState<any[]>([]);
    const [isSidebarOpen, setIsSidebarOpen] = useState(true);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    useEffect(() => {
        loadSessions();
    }, []);

    const loadSessions = async () => {
        try {
            const data = await listSessions();
            setSessions(data.sessions || []);
        } catch (error) {
            console.error("Failed to load sessions", error);
        }
    };

    const handleSend = async () => {
        if (!input.trim() || isLoading) return;

        const userMsg: ChatMessage = { role: 'user', content: input };
        setMessages(prev => [...prev, userMsg]);
        setInput('');
        setIsLoading(true);

        try {
            const response = await sendMessage(sessionId, userMsg.content);
            setSessionId(response.session_id);

            const newMessages = response.messages.filter(m => m.role !== 'user');
            setMessages(prev => [...prev, ...newMessages]);

            // Refresh sessions list if this was a new session
            if (!sessionId) {
                await loadSessions();
            }
        } catch (error) {
            console.error('Failed to send message:', error);
            setMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, I encountered an error. Please try again.' }]);
        } finally {
            setIsLoading(false);
        }
    };

    const handleNewSession = async () => {
        try {
            const session = await createSession();
            setSessionId(session.session_id);
            setMessages([]);
            await loadSessions();
            if (window.innerWidth < 768) {
                setIsSidebarOpen(false);
            }
        } catch (error) {
            console.error("Failed to create session", error);
        }
    };

    const handleSelectSession = async (id: string) => {
        setSessionId(id);
        if (window.innerWidth < 768) {
            setIsSidebarOpen(false);
        }
        try {
            const sessionData = await getSession(id);
            if (sessionData && sessionData.messages) {
                setMessages(sessionData.messages.map((m: any) => ({
                    role: m.role,
                    content: m.content || m.content_md || "",
                    timestamp: m.timestamp
                })));
            } else {
                setMessages([]);
            }
        } catch (error) {
            console.error("Failed to load session", error);
        }
    };

    const handleDeleteSession = async (id: string) => {
        if (!confirm("Are you sure you want to delete this chat?")) return;
        try {
            await deleteSession(id);
            if (sessionId === id) {
                setSessionId(null);
                setMessages([]);
            }
            await loadSessions();
        } catch (error) {
            console.error("Failed to delete session", error);
        }
    };

    const [sidebarWidth, setSidebarWidth] = useState(400);
    const [isResizing, setIsResizing] = useState(false);

    useEffect(() => {
        const handleMouseMove = (e: MouseEvent) => {
            if (isResizing) {
                const newWidth = Math.max(200, Math.min(600, e.clientX));
                setSidebarWidth(newWidth);
            }
        };

        const handleMouseUp = () => {
            setIsResizing(false);
        };

        if (isResizing) {
            window.addEventListener('mousemove', handleMouseMove);
            window.addEventListener('mouseup', handleMouseUp);
        }

        return () => {
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
        };
    }, [isResizing]);

    return (
        <div className="flex h-screen bg-[#0E0C15] text-gray-100 font-sans overflow-hidden">
            {isSidebarOpen && (
                <div
                    className="fixed inset-0 bg-[#0E0C15]/80 backdrop-blur-sm z-40 md:hidden"
                    onClick={() => setIsSidebarOpen(false)}
                />
            )}

            <Sidebar
                isOpen={isSidebarOpen}
                onToggle={() => setIsSidebarOpen(!isSidebarOpen)}
                sessions={sessions}
                activeSessionId={sessionId}
                onSelectSession={handleSelectSession}
                onNewSession={handleNewSession}
                onDeleteSession={handleDeleteSession}
                width={sidebarWidth}
            />

            <div
                className="w-1 bg-[#252134] hover:bg-[#AC6AFF]/50 cursor-col-resize transition-colors hidden md:block"
                onMouseDown={() => setIsResizing(true)}
            />

            <div className="flex-1 flex flex-col h-full relative bg-[#15131D] md:rounded-l-3xl md:border-l md:border-y border-[#252134] overflow-hidden shadow-2xl">
                <header className="h-16 border-b border-[#252134] flex items-center px-6 justify-between bg-[#15131D]/80 backdrop-blur-md sticky top-0 z-10">
                    <div className="flex items-center gap-3">
                        <button
                            onClick={() => setIsSidebarOpen(!isSidebarOpen)}
                            className="text-[#757185] hover:text-white transition-colors p-1.5 hover:bg-[#252134] rounded-lg"
                            title={isSidebarOpen ? "Close Sidebar" : "Open Sidebar"}
                        >
                            <Menu size={18} />
                        </button>
                        <div className="text-xs font-bold text-[#757185]">HireX <span className="text-[#252134] mx-1.5">/</span> <span className="text-white">Chat</span></div>
                    </div>
                    <div className="flex items-center gap-2">
                        <div className="w-8 h-8 rounded-full bg-gradient-to-r from-[#AC6AFF] to-[#4687F1] p-[2px]">
                            <div className="w-full h-full rounded-full bg-[#0E0C15] flex items-center justify-center">
                                <User size={13} className="text-white" />
                            </div>
                        </div>
                    </div>
                </header>

                <div className="flex-1 overflow-y-auto p-4 md:p-8 scrollbar-thin scrollbar-thumb-[#252134] scrollbar-track-transparent">
                    <div className="max-w-4xl mx-auto space-y-8">
                        {messages.length === 0 && (
                            <div className="flex-1 flex flex-col items-center justify-center p-4 text-center animate-in fade-in duration-500">
                                <div className="w-14 h-14 rounded-2xl flex items-center justify-center mb-4 shadow-2xl shadow-[#AC6AFF]/30 overflow-hidden">
                                    <img src="/hirex-logo.png" alt="HireX Logo" className="w-full h-full object-cover" />
                                </div>
                                <h1 className="text-2xl md:text-3xl font-bold text-white mb-3 font-sora tracking-tight">
                                    Welcome to <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#AC6AFF] to-[#4687F1]">HireX</span>
                                </h1>
                                <p className="text-xs md:text-sm text-[#757185] max-w-xl mb-5 leading-relaxed">
                                    Your AI-powered recruitment assistant. Follow these simple steps to find your perfect candidate.
                                </p>

                                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 w-full max-w-2xl">
                                    {[
                                        {
                                            step: '01',
                                            title: 'Define Requirements',
                                            desc: 'Start by describing the job role, required skills, and experience levels.',
                                            icon: <Briefcase size={24} />,
                                            action: 'I need a Senior Python Developer with 5+ years of experience...'
                                        },
                                        {
                                            step: '02',
                                            title: 'Screen Candidates',
                                            desc: 'Ask AI to analyze resumes against your criteria and rank the best matches.',
                                            icon: <Search size={24} />,
                                            action: 'Screen the candidates for this role'
                                        },
                                        {
                                            step: '03',
                                            title: 'Discuss Results',
                                            desc: 'Deep dive into candidate profiles, ask for summaries, or draft emails.',
                                            icon: <MessageSquare size={24} />,
                                            action: 'Summarize the top 3 candidates'
                                        }
                                    ].map((item) => (
                                        <button
                                            key={item.step}
                                            onClick={() => setInput(item.action)}
                                            className="group relative flex flex-col items-start p-4 bg-[#15131D] hover:bg-[#252134] border border-[#252134] hover:border-[#AC6AFF]/30 rounded-2xl text-left transition-all hover:-translate-y-1 shadow-lg shadow-black/20 h-full"
                                        >
                                            <div className="absolute top-3 right-3 text-xs font-bold text-[#757185] opacity-15 group-hover:opacity-40 font-mono text-[32px] leading-none select-none">
                                                {item.step}
                                            </div>
                                            <div className="w-10 h-10 bg-[#0E0C15] rounded-xl flex items-center justify-center text-[#AC6AFF] group-hover:scale-110 transition-transform border border-[#252134] mb-3">
                                                {item.icon}
                                            </div>
                                            <div className="font-bold text-white text-sm mb-2">{item.title}</div>
                                            <div className="text-xs text-[#757185] leading-relaxed mb-3 flex-1">{item.desc}</div>
                                            <div className="flex items-center gap-1.5 text-[10px] font-bold text-[#AC6AFF] uppercase tracking-wider group-hover:gap-2 transition-all">
                                                <span>Try it now</span>
                                                <ArrowRight size={11} />
                                            </div>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        )}

                        {messages.map((msg, idx) => (
                            <div
                                key={idx}
                                className={clsx(
                                    "flex gap-6 animate-in slide-in-from-bottom-2 duration-300",
                                    msg.role === 'user' ? "justify-end" : "justify-start"
                                )}
                            >
                                {msg.role === 'assistant' && (
                                    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#AC6AFF] to-[#4687F1] flex items-center justify-center flex-shrink-0 shadow-lg shadow-[#AC6AFF]/20">
                                        <Bot size={20} className="text-white" />
                                    </div>
                                )}

                                <div className={clsx(
                                    "max-w-[75%] rounded-2xl px-4 py-3 shadow-md",
                                    msg.role === 'user'
                                        ? "bg-[#1E1E2E] border-l-4 border-[#AC6AFF] text-gray-100 rounded-br-sm"
                                        : "bg-[#1E1E2E] border-l-4 border-[#4687F1] text-gray-100 rounded-bl-sm"
                                )}>
                                    <div className="prose prose-invert max-w-none leading-relaxed text-xs">
                                        <ReactMarkdown
                                            remarkPlugins={[remarkGfm]}
                                            components={{
                                                p: ({ node, ...props }) => <p className="mb-2 last:mb-0 leading-relaxed" {...props} />,
                                                ul: ({ node, ...props }) => <ul className="list-disc pl-4 mb-2 space-y-0.5 marker:text-[#AC6AFF]" {...props} />,
                                                ol: ({ node, ...props }) => <ol className="list-decimal pl-4 mb-2 space-y-0.5 marker:text-[#4687F1]" {...props} />,
                                                li: ({ node, ...props }) => <li className="leading-relaxed" {...props} />,
                                                h1: ({ node, ...props }) => <h1 className="text-lg font-bold mb-2.5 mt-3.5 text-white border-b border-[#AC6AFF] pb-1.5" {...props} />,
                                                h2: ({ node, ...props }) => <h2 className="text-base font-extrabold mb-2 mt-3 text-white" {...props} />,
                                                h3: ({ node, ...props }) => <h3 className="text-sm font-semibold mb-1.5 mt-2.5 text-gray-200" {...props} />,
                                                code: ({ node, ...props }) => <code className="bg-[#0E0C15] px-1 py-0.5 rounded text-[11px] font-mono text-[#AC6AFF] border border-[#252134]" {...props} />,
                                                pre: ({ node, ...props }) => <pre className="bg-[#0E0C15] p-2.5 rounded-lg overflow-x-auto mb-2.5 border border-[#252134] text-[11px]" {...props} />,
                                                strong: ({ node, ...props }) => <strong className="font-extrabold text-white text-[13px]" {...props} />,
                                                em: ({ node, ...props }) => <em className="italic text-gray-300" {...props} />,
                                                blockquote: ({ node, ...props }) => <blockquote className="border-l-2 border-[#AC6AFF] pl-2.5 italic text-gray-300 my-2" {...props} />,
                                                table: ({ node, ...props }) => (
                                                    <div className="overflow-x-auto my-4 rounded-xl border border-[#252134]">
                                                        <table className="w-full border-collapse" {...props} />
                                                    </div>
                                                ),
                                                thead: ({ node, ...props }) => <thead className="bg-gradient-to-r from-[#AC6AFF]/10 to-[#4687F1]/10 border-b-2 border-[#AC6AFF]" {...props} />,
                                                tbody: ({ node, ...props }) => <tbody className="divide-y divide-[#252134]" {...props} />,
                                                tr: ({ node, ...props }) => <tr className="hover:bg-[#252134]/50 transition-colors" {...props} />,
                                                th: ({ node, ...props }) => <th className="px-3 py-2.5 text-left text-xs font-bold text-white" {...props} />,
                                                td: ({ node, ...props }) => <td className="px-3 py-2.5 text-[11px]" {...props} />,
                                            }}
                                        >
                                            {msg.content}
                                        </ReactMarkdown>
                                    </div>
                                </div>

                                {msg.role === 'user' && (
                                    <div className="w-10 h-10 rounded-xl bg-[#15131D] border border-[#252134] flex items-center justify-center flex-shrink-0">
                                        <User size={20} className="text-[#757185]" />
                                    </div>
                                )}
                            </div>
                        ))}

                        {isLoading && (
                            <div className="flex gap-4">
                                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#AC6AFF] to-[#4687F1] flex items-center justify-center flex-shrink-0">
                                    <Bot size={20} className="text-white" />
                                </div>
                                <div className="bg-[#15131D] border border-[#252134] rounded-2xl rounded-bl-sm px-4 py-3 flex items-center gap-3">
                                    <Loader2 className="w-4 h-4 animate-spin text-[#AC6AFF]" />
                                    <span className="text-xs text-[#757185] font-medium">Thinking...</span>
                                </div>
                            </div>
                        )}
                        <div ref={messagesEndRef} />
                    </div>
                </div>

                <div className="p-8 bg-[#15131D]">
                    <div className="max-w-4xl mx-auto relative">
                        <div className="relative bg-[#15131D] rounded-3xl border border-[#252134] shadow-2xl shadow-black/50 transition-all focus-within:border-[#AC6AFF]/50 focus-within:ring-1 focus-within:ring-[#AC6AFF]/20">
                            <textarea
                                value={input}
                                onChange={(e) => setInput(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter' && !e.shiftKey) {
                                        e.preventDefault();
                                        handleSend();
                                    }
                                }}
                                placeholder="Ask anything about the candidates..."
                                className="w-full bg-transparent text-white rounded-3xl pl-8 pr-16 py-4 resize-none focus:outline-none placeholder-[#757185] scrollbar-hide text-sm"
                                rows={1}
                                style={{ minHeight: '48px', maxHeight: '120px' }}
                                disabled={isLoading}
                            />
                            <button
                                onClick={handleSend}
                                disabled={isLoading || !input.trim()}
                                className="absolute right-2.5 bottom-2.5 p-2 bg-[#AC6AFF] hover:bg-[#9B51E0] text-white rounded-lg disabled:opacity-50 disabled:hover:bg-[#AC6AFF] transition-all shadow-lg shadow-[#AC6AFF]/20"
                            >
                                <Send size={18} />
                            </button>
                        </div>
                        <div className="text-center mt-4">
                            <p className="text-[10px] text-[#757185] font-bold uppercase tracking-widest">Powered by HireX AI</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
