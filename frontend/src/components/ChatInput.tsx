'use client';

import { useState, useRef } from 'react';

interface ImageData {
  base64: string;
  mediaType: string;
  preview: string;
}

interface ChatInputProps {
  onSend: (query: string, image?: ImageData) => void;
  isLoading: boolean;
  disabled: boolean;
}

export default function ChatInput({ onSend, isLoading, disabled }: ChatInputProps) {
  const [query, setQuery] = useState('');
  const [image, setImage] = useState<ImageData | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const canSend = query.trim().length > 0 && !isLoading && !disabled;

  function handleSubmit(e?: React.FormEvent) {
    e?.preventDefault();
    if (!canSend) return;

    onSend(query.trim(), image || undefined);
    setQuery('');
    setImage(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
    setTimeout(() => inputRef.current?.focus(), 100);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSubmit();
    }
  }

  function handleImageSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    const allowedTypes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];
    if (!allowedTypes.includes(file.type)) return;
    if (file.size > 5 * 1024 * 1024) return;

    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      const base64 = result.split(',')[1];
      setImage({ base64, mediaType: file.type, preview: result });
    };
    reader.readAsDataURL(file);
  }

  function handleRemoveImage() {
    setImage(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  return (
    <div className="bg-white border-t-2 border-[#e0e0e0] safe-bottom">
      {/* Image preview */}
      {image && (
        <div className="px-4 pt-3">
          <div className="relative inline-block">
            <img
              src={image.preview}
              alt="Standort-Foto"
              className="w-14 h-14 object-cover rounded-xl border border-[#ddd]"
            />
            <button
              type="button"
              onClick={handleRemoveImage}
              className="absolute -top-1.5 -right-1.5 w-5 h-5 bg-[#333] text-white rounded-full text-xs flex items-center justify-center shadow"
              aria-label="Foto entfernen"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Input row */}
      <form onSubmit={handleSubmit} className="flex items-center gap-2.5 px-3 py-3">
        {/* Camera button */}
        <label className="flex-shrink-0 w-11 h-11 rounded-full bg-[#f3f3f3] border border-[#d0d0d0] flex items-center justify-center text-[#555] active:scale-95 active:bg-[#e8e8e8] transition-all cursor-pointer">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z" />
            <circle cx="12" cy="13" r="4" />
          </svg>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/gif,image/webp"
            capture="environment"
            onChange={handleImageSelect}
            className="sr-only"
            disabled={isLoading}
          />
        </label>

        {/* Text input */}
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={disabled ? 'Wähle einen Bahnhof...' : 'Wohin möchtest du?'}
          disabled={disabled || isLoading}
          className="flex-1 h-11 px-4 bg-[#f7f7f7] border border-[#d0d0d0] rounded-full text-[14px] text-[#111] font-medium placeholder:text-[#999] placeholder:font-normal focus:outline-none focus:ring-2 focus:ring-[#e30613]/30 focus:border-[#e30613] disabled:opacity-40 transition-all"
        />

        {/* Send button */}
        <button
          type="submit"
          disabled={!canSend}
          className={`flex-shrink-0 w-11 h-11 rounded-full flex items-center justify-center transition-all active:scale-90 ${
            canSend
              ? 'bg-[#e30613] text-white shadow-md'
              : 'bg-[#f3f3f3] text-[#bbb] border border-[#d0d0d0]'
          }`}
          aria-label="Senden"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
          </svg>
        </button>
      </form>
    </div>
  );
}
