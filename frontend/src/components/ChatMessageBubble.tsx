'use client';

import dynamic from 'next/dynamic';
import { ChatMessage } from '../types';
import RouteSummary from './RouteSummary';

const RouteMap = dynamic(() => import('./RouteMap'), { ssr: false });

interface ChatMessageBubbleProps {
  message: ChatMessage;
}

export default function ChatMessageBubble({ message }: ChatMessageBubbleProps) {
  const isUser = message.role === 'user';

  // Loading animation
  if (message.isLoading) {
    return (
      <div className="flex justify-start animate-fade-in-up">
        <div className="px-5 py-4 rounded-2xl rounded-bl-sm bg-white shadow-sm border border-[#ddd]">
          <div className="flex items-center gap-2">
            <div className="w-2.5 h-2.5 rounded-full bg-[#e30613] typing-dot" />
            <div className="w-2.5 h-2.5 rounded-full bg-[#e30613] typing-dot" />
            <div className="w-2.5 h-2.5 rounded-full bg-[#e30613] typing-dot" />
          </div>
        </div>
      </div>
    );
  }

  // Error message
  if (message.error) {
    return (
      <div className="flex justify-start animate-fade-in-up">
        <div className="max-w-[85%] px-4 py-3 rounded-2xl rounded-bl-sm bg-[#fff5f5] border border-[#fca5a5]">
          <div className="flex items-start gap-2">
            <span className="mt-0.5 flex-shrink-0 text-base">⚠️</span>
            <p className="text-[13px] text-[#7f1d1d] font-medium leading-relaxed">{message.error}</p>
          </div>
        </div>
      </div>
    );
  }

  // User message
  if (isUser) {
    return (
      <div className="flex justify-end animate-fade-in-up">
        <div className="max-w-[80%] space-y-2">
          {message.image && (
            <div className="flex justify-end">
              <img
                src={message.image}
                alt="Standort-Foto"
                className="w-36 h-36 object-cover rounded-2xl shadow-md border border-[#ddd]"
              />
            </div>
          )}
          <div className="px-4 py-3 rounded-2xl rounded-br-sm bg-[#e30613] shadow-sm">
            <p className="text-[14px] text-white font-medium leading-relaxed">{message.content}</p>
          </div>
        </div>
      </div>
    );
  }

  // Instructions response with embedded map
  if (message.instructions && message.instructions.length > 0) {
    const hasRoute = message.route && message.route.length > 0;

    return (
      <div className="flex justify-start animate-fade-in-up">
        <div className="max-w-[92%] w-full rounded-2xl rounded-bl-sm bg-white border border-[#ddd] shadow-sm overflow-hidden">
          {/* Map at the top */}
          {hasRoute && (
            <div className="border-b border-[#ddd]">
              <RouteMap route={message.route!} turnPoints={message.turnPoints || []} />
            </div>
          )}

          {/* Summary */}
          <RouteSummary route={message.route || []} instructions={message.instructions} startInside={message.startInside} endInside={message.endInside} />

          {/* Header */}
          <div className="px-4 py-3 border-b border-[#eee] bg-[#fafafa]">
            <p className="text-[14px] font-bold text-[#111]">🗺️ Deine Route</p>
          </div>

          {/* Steps */}
          <div className="px-4 py-3 space-y-3">
            {message.instructions.map((instruction, index) => (
              <div key={index} className="flex gap-3">
                <div className="flex-shrink-0 w-7 h-7 rounded-full bg-[#e30613] flex items-center justify-center mt-0.5 shadow-sm">
                  <span className="text-xs font-bold text-white">{index + 1}</span>
                </div>
                <p className="text-[13px] text-[#222] leading-relaxed pt-1 font-medium">{instruction}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // Plain assistant message
  return (
    <div className="flex justify-start animate-fade-in-up">
      <div className="max-w-[80%] px-4 py-3 rounded-2xl rounded-bl-sm bg-white border border-[#ddd] shadow-sm">
        <p className="text-[14px] text-[#111] leading-relaxed font-medium whitespace-pre-line">{message.content}</p>
      </div>
    </div>
  );
}
