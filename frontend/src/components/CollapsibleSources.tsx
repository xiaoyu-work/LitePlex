import React, { useState } from 'react';
import { ChevronDown, Globe, ExternalLink } from 'lucide-react';

interface Source {
  index: number;
  title: string;
  url: string;
}

interface CollapsibleSourcesProps {
  sources: Source[];
}

export const CollapsibleSources: React.FC<CollapsibleSourcesProps> = ({ sources }) => {
  const [isOpen, setIsOpen] = useState(true); // Default to open
  
  if (!sources || sources.length === 0) {
    return null;
  }

  const getHostname = (url: string) => {
    try {
      return new URL(url).hostname.replace('www.', '');
    } catch {
      return url;
    }
  };

  return (
    <div className="w-full mt-4">
      {/* Accordion Header */}
      <div
        className={`
          py-3 px-4 hover:no-underline group cursor-pointer
          bg-muted/30
          border border-border
          ${isOpen ? 'rounded-t-lg' : 'rounded-lg'}
          transition-all duration-200
        `}
        onClick={() => setIsOpen(!isOpen)}
      >
        <div className="flex items-center justify-between w-full">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-md bg-muted">
              <Globe className="h-3.5 w-3.5 text-muted-foreground" />
            </div>
            <h2 className="font-medium text-sm text-foreground">Sources</h2>
          </div>
          <div className="flex items-center gap-2">
            <span className="rounded-full text-xs px-2.5 py-0.5 bg-muted text-muted-foreground">
              {sources.length}
            </span>
            <ChevronDown
              className={`
                h-4 w-4 text-muted-foreground shrink-0 transition-transform duration-200
                ${isOpen ? 'rotate-180' : ''}
              `}
            />
          </div>
        </div>
      </div>

      {/* Collapsible Content */}
      {isOpen && (
        <div
          className="
            bg-transparent
            border-x border-b border-border
            rounded-b-lg
            overflow-hidden
          "
        >
          <div className="p-4 space-y-1 max-h-96 overflow-y-auto">
            {sources.map((source) => (
              <a
                key={source.index}
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                className="block"
              >
                <div className="
                  group relative
                  py-3 px-2 transition-all duration-200
                  hover:bg-muted/50 rounded-lg
                ">
                  <div className="flex items-start gap-3">
                    {/* Source icon */}
                    <div className="relative w-6 h-6 rounded-sm flex items-center justify-center overflow-hidden shrink-0 mt-0.5">
                      <Globe className="w-4 h-4 text-muted-foreground" />
                    </div>

                    {/* Content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-muted-foreground font-medium">{source.index}</span>
                            <h3 className="font-normal text-sm text-foreground line-clamp-1 group-hover:text-primary transition-colors">
                              {source.title}
                            </h3>
                          </div>
                          <div className="flex items-center gap-1.5 text-xs text-muted-foreground mt-1">
                            <span className="truncate">{getHostname(source.url)}</span>
                            <ExternalLink className="w-3 h-3 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
