'use client';

import { useState, useRef } from 'react';

interface ImageData {
  base64: string;
  mediaType: string;
  preview: string;
}

interface NavigationInputProps {
  zoneID: string;
  onSubmit: (query: string, image?: ImageData) => void;
  isLoading?: boolean;
}

export default function NavigationInput({
  zoneID,
  onSubmit,
  isLoading = false,
}: NavigationInputProps) {
  const [query, setQuery] = useState('');
  const [validationMessage, setValidationMessage] = useState('');
  const [image, setImage] = useState<ImageData | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const isQueryEmpty = query.trim().length === 0;
  const isStationMissing = zoneID === '';
  const isSubmitDisabled = isStationMissing || isQueryEmpty || isLoading;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    if (isQueryEmpty) {
      setValidationMessage('Bitte geben Sie eine Beschreibung ein');
      return;
    }

    if (isStationMissing) {
      setValidationMessage('Bitte wählen Sie einen Bahnhof');
      return;
    }

    setValidationMessage('');
    onSubmit(query.trim(), image || undefined);
  }

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    setQuery(e.target.value);
    if (validationMessage) {
      setValidationMessage('');
    }
  }

  function handleImageSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    // Validate file type
    const allowedTypes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];
    if (!allowedTypes.includes(file.type)) {
      setValidationMessage('Ungültiger Bildtyp. Erlaubt: JPEG, PNG, GIF, WebP');
      return;
    }

    // Validate file size (max 5 MB)
    if (file.size > 5 * 1024 * 1024) {
      setValidationMessage('Das Bild ist zu groß (max. 5 MB)');
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      // result is "data:<mediaType>;base64,<data>"
      const base64 = result.split(',')[1];
      setImage({
        base64,
        mediaType: file.type,
        preview: result,
      });
      setValidationMessage('');
    };
    reader.readAsDataURL(file);
  }

  function handleRemoveImage() {
    setImage(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }

  return (
    <form onSubmit={handleSubmit} className="w-full" noValidate>
      <div className="flex flex-col gap-2">
        <label htmlFor="navigation-query" className="text-sm font-medium">
          Wohin möchten Sie navigieren?
        </label>
        <div className="flex gap-2">
          <input
            id="navigation-query"
            type="text"
            value={query}
            onChange={handleInputChange}
            maxLength={500}
            placeholder={
              image
                ? 'z.B. Ich möchte zum Starbucks'
                : 'z.B. Ich bin am Gleis 5 und möchte zum Starbucks'
            }
            className="flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            aria-describedby="validation-message"
            disabled={isLoading}
          />
          <button
            type="submit"
            disabled={isSubmitDisabled}
            className="min-w-[44px] min-h-[44px] px-4 py-2 bg-blue-600 text-white font-medium rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
          >
            {isLoading ? 'Lädt...' : 'Navigieren'}
          </button>
        </div>

        {/* Image upload section */}
        <div className="flex items-center gap-2 mt-1">
          <label
            htmlFor="position-image"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-gray-700 bg-gray-100 border border-gray-300 rounded-md cursor-pointer hover:bg-gray-200 focus-within:ring-2 focus-within:ring-blue-500 transition-colors"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-4 w-4"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"
              />
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15 13a3 3 0 11-6 0 3 3 0 016 0z"
              />
            </svg>
            Foto vom Standort
            <input
              ref={fileInputRef}
              id="position-image"
              type="file"
              accept="image/jpeg,image/png,image/gif,image/webp"
              onChange={handleImageSelect}
              className="sr-only"
              disabled={isLoading}
            />
          </label>
          {image && (
            <span className="text-sm text-green-700">
              Foto hinzugefügt — Startposition wird aus dem Bild bestimmt
            </span>
          )}
        </div>

        {/* Image preview */}
        {image && (
          <div className="relative inline-block mt-1">
            <img
              src={image.preview}
              alt="Foto vom aktuellen Standort"
              className="h-20 w-20 object-cover rounded-md border border-gray-300"
            />
            <button
              type="button"
              onClick={handleRemoveImage}
              className="absolute -top-2 -right-2 w-5 h-5 bg-red-500 text-white rounded-full text-xs flex items-center justify-center hover:bg-red-600 focus:outline-none focus:ring-2 focus:ring-red-500"
              aria-label="Foto entfernen"
            >
              ×
            </button>
          </div>
        )}

        <div
          id="validation-message"
          aria-live="polite"
          className="min-h-[1.25rem] text-sm text-red-600"
        >
          {validationMessage}
        </div>
      </div>
    </form>
  );
}
