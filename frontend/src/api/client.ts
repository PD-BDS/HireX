import axios from 'axios';

const api = axios.create({
    baseURL: import.meta.env.PROD
        ? 'https://hirex-backend-xyz.onrender.com/api/v1'  // Your backend URL
        : '/api/v1',
    timeout: 900000,
    headers: {
        'Content-Type': 'application/json',
    },
});

export interface ChatMessage {
    role: 'user' | 'assistant';
    content: string;
    timestamp?: string;
}

export interface ChatResponse {
    session_id: string;
    messages: ChatMessage[];
    status: string;
    error?: string;
}

export const sendMessage = async (sessionId: string | null, message: string): Promise<ChatResponse> => {
    const response = await api.post<ChatResponse>('/chat', {
        session_id: sessionId,
        message,
    });
    return response.data;
};

export const createSession = async () => {
    const response = await api.post('/sessions');
    return response.data;
};

export const deleteSession = async (sessionId: string) => {
    const response = await api.delete(`/sessions/${sessionId}`);
    return response.data;
};

export const getSession = async (sessionId: string) => {
    const response = await api.get(`/sessions/${sessionId}`);
    return response.data;
};

export const updateSessionConfig = async (
    sessionId: string,
    config: {
        top_k?: number;
        scoring_weights?: Record<string, number>;
        feature_weights?: Record<string, number>;
    }
) => {
    const response = await api.put(`/sessions/${sessionId}/config`, config);
    return response.data;
};

export const listFiles = async (prefix?: string) => {
    const response = await api.get('/files', { params: { prefix } });
    return response.data;
};

export const listSessions = async () => {
    const response = await api.get('/sessions');
    return response.data;
};
