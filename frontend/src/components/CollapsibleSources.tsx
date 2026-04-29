import React, { useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2, ChevronDown, ExternalLink, Globe, Quote } from 'lucide-react';

interface Source {
  index: number;
  title: string;
  url: string;
  evidence?: SourceEvidence[];
  citationCheck?: CitationCheck;
}

interface SourceEvidence {
  text: string;
  score?: number;
}

type CitationConfidence = 'supported' | 'partial' | 'low' | 'uncited';

interface CitationCheck {
  cited: boolean;
  confidence: CitationConfidence;
  reason: string;
  claims?: string[];
  matchedExcerpt?: string;
  overlapTerms?: string[];
  checkedClaim?: string;
}

interface CollapsibleSourcesProps {
  sources: Source[];
}

export const CollapsibleSources: React.FC<CollapsibleSourcesProps> = ({ sources }) => {
  const [isOpen, setIsOpen] = useState(true); // Default to open
  const [expandedSources, setExpandedSources] = useState<Set<number>>(new Set());

  useEffect(() => {
    const expandSourceFromHash = () => {
      const match = window.location.hash.match(/^#source-(\d+)$/);
      if (!match) {
        return;
      }

      const sourceIndex = Number(match[1]);
      if (!Number.isInteger(sourceIndex)) {
        return;
      }

      setIsOpen(true);
      setExpandedSources(prev => new Set(prev).add(sourceIndex));
    };

    expandSourceFromHash();
    window.addEventListener('hashchange', expandSourceFromHash);
    return () => window.removeEventListener('hashchange', expandSourceFromHash);
  }, []);
  
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

  const toggleSource = (sourceIndex: number) => {
    setExpandedSources(prev => {
      const next = new Set(prev);
      if (next.has(sourceIndex)) {
        next.delete(sourceIndex);
      } else {
        next.add(sourceIndex);
      }
      return next;
    });
  };

  const getConfidenceMeta = (check?: CitationCheck) => {
    switch (check?.confidence) {
      case 'supported':
        return {
          label: 'Supported',
          className: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/20',
          icon: CheckCircle2
        };
      case 'partial':
        return {
          label: 'Partial',
          className: 'bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/20',
          icon: AlertCircle
        };
      case 'low':
        return {
          label: 'Low evidence',
          className: 'bg-red-500/10 text-red-700 dark:text-red-300 border-red-500/20',
          icon: AlertCircle
        };
      default:
        return {
          label: 'Context',
          className: 'bg-muted text-muted-foreground border-border',
          icon: Quote
        };
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
            {sources.map((source) => {
              const evidence = source.evidence || [];
              const isExpanded = expandedSources.has(source.index);
              const confidence = getConfidenceMeta(source.citationCheck);
              const ConfidenceIcon = confidence.icon;

              return (
              <div
                key={source.index}
                id={`source-${source.index}`}
                className="scroll-mt-24"
              >
                <div className="
                  group relative
                  py-3 px-2 transition-all duration-200
                  hover:bg-muted/50 rounded-lg
                ">
                  <div className="flex items-start gap-3">
                    <div className="relative w-6 h-6 rounded-sm flex items-center justify-center overflow-hidden shrink-0 mt-0.5">
                      <Globe className="w-4 h-4 text-muted-foreground" />
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-muted-foreground font-medium">{source.index}</span>
                            <button
                              type="button"
                              onClick={() => evidence.length > 0 && toggleSource(source.index)}
                              className="font-normal text-sm text-foreground line-clamp-1 text-left group-hover:text-primary transition-colors"
                            >
                              {source.title}
                            </button>
                          </div>
                          <div className="flex items-center gap-1.5 text-xs text-muted-foreground mt-1">
                            <span className="truncate">{getHostname(source.url)}</span>
                            <a
                              href={source.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex hover:text-primary"
                              aria-label={`Open source ${source.index}`}
                            >
                              <ExternalLink className="w-3 h-3 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
                            </a>
                          </div>
                          <div className="flex flex-wrap items-center gap-2 mt-2">
                            <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] ${confidence.className}`}>
                              <ConfidenceIcon className="w-3 h-3" />
                              {confidence.label}
                            </span>
                            {evidence.length > 0 && (
                              <button
                                type="button"
                                onClick={() => toggleSource(source.index)}
                                className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline"
                              >
                                {isExpanded ? 'Hide evidence' : `Show evidence (${evidence.length})`}
                                <ChevronDown className={`w-3 h-3 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {isExpanded && evidence.length > 0 && (
                    <div className="mt-3 ml-9 space-y-3 rounded-md border border-border bg-background/70 p-3">
                      {source.citationCheck?.checkedClaim && (
                        <div className="text-xs text-muted-foreground">
                          <span className="font-medium text-foreground">Checked claim:</span>{' '}
                          {source.citationCheck.checkedClaim}
                        </div>
                      )}
                      <div className="space-y-2">
                        {evidence.map((item, index) => (
                          <blockquote
                            key={`${source.index}-${index}`}
                            className="border-l-2 border-primary/40 pl-3 text-xs leading-relaxed text-muted-foreground"
                          >
                            {item.text}
                          </blockquote>
                        ))}
                      </div>
                      {source.citationCheck?.reason && (
                        <div className="text-[11px] text-muted-foreground">
                          {source.citationCheck.reason}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
