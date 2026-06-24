'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import ChatHeader from '../components/ChatHeader';
import ChatMessageBubble from '../components/ChatMessageBubble';
import ChatInput from '../components/ChatInput';
import { ChatMessage, NavigateResponse } from '../types';

export default function Home() {
  const [selectedZoneID, setSelectedZoneID] = useState('');
  const [selectedStationName, setSelectedStationName] = useState('');
  const [handicapped, setHandicapped] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Add welcome message on mount
  useEffect(() => {
    setMessages([
      {
        id: 'welcome',
        role: 'assistant',
        content: 'Hallo! 👋 Ich helfe dir, dich im Bahnhof zurechtzufinden. Wähle oben einen Bahnhof aus und sag mir, wohin du möchtest.',
        timestamp: new Date(),
      },
    ]);
  }, []);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleStationChange = useCallback((zoneID: string, name: string) => {
    setSelectedZoneID(zoneID);
    setSelectedStationName(name);
  }, []);

  async function handleSend(query: string, image?: { base64: string; mediaType: string; preview: string }) {
    if (!selectedZoneID) {
      setMessages(prev => [...prev, {
        id: Date.now().toString(),
        role: 'assistant',
        content: 'Bitte wähle zuerst einen Bahnhof aus. ☝️',
        timestamp: new Date(),
      }]);
      return;
    }

    // Add user message
    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: query,
      timestamp: new Date(),
      image: image?.preview,
    };
    setMessages(prev => [...prev, userMessage]);

    // Add loading message
    const loadingId = (Date.now() + 1).toString();
    setMessages(prev => [...prev, {
      id: loadingId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      isLoading: true,
    }]);

    setIsLoading(true);

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 60000);

    try {
      const requestBody: Record<string, unknown> = {
        zoneID: selectedZoneID,
        query,
        handicapped,
      };

      if (image) {
        requestBody.image = image.base64;
        requestBody.image_media_type = image.mediaType;
      }

      const response = await fetch('/api/navigate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
        signal: controller.signal,
      });

      const data: NavigateResponse = await response.json();

      // Replace loading message with result
      setMessages(prev => prev.map(msg =>
        msg.id === loadingId
          ? {
              ...msg,
              isLoading: false,
              content: data.error || '',
              instructions: data.error ? undefined : data.instructions,
              route: data.route,
              turnPoints: data.turn_points,
              startInside: data.start_inside,
              endInside: data.end_inside,
              error: data.error || undefined,
            }
          : msg
      ));
    } catch (err) {
      const errorMsg = err instanceof DOMException && err.name === 'AbortError'
        ? 'Die Anfrage hat zu lange gedauert. Versuch es nochmal.'
        : 'Verbindung fehlgeschlagen. Bitte prüfe deine Internetverbindung.';

      setMessages(prev => prev.map(msg =>
        msg.id === loadingId
          ? { ...msg, isLoading: false, content: errorMsg, error: errorMsg }
          : msg
      ));
    } finally {
      clearTimeout(timeoutId);
      setIsLoading(false);
    }
  }

  return (
    <div className="h-full flex flex-col max-w-lg mx-auto bg-[var(--surface-chat)] shadow-xl">
      {/* Header */}
      <ChatHeader
        selectedZoneID={selectedZoneID}
        selectedStationName={selectedStationName}
        handicapped={handicapped}
        onStationChange={handleStationChange}
        onHandicappedChange={setHandicapped}
      />

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.map(msg => (
          <ChatMessageBubble key={msg.id} message={msg} />
        ))}

        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <ChatInput
        onSend={handleSend}
        isLoading={isLoading}
        disabled={!selectedZoneID}
      />
    </div>
  );
}
