import React, { useState, useEffect } from 'react';
import { MessageSquare, Plus, Trash2, Briefcase, X, Search, Sliders, HelpCircle, ChevronDown, ChevronUp } from 'lucide-react';
import clsx from 'clsx';
import { updateSessionConfig } from '../api/client';

interface SidebarProps {
  isOpen: boolean;
  onToggle: () => void;
  sessions: any[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onDeleteSession: (id: string) => void;
  width?: number;
}

const WEIGHT_OPTIONS = [
  { label: 'Low', value: 0.5, color: '#4687F1' },
  { label: 'Medium', value: 1.0, color: '#AC6AFF' },
  { label: 'High', value: 1.5, color: '#FF5E62' },
];

const SCORING_OPTIONS = [
  { label: 'Balanced', value: { semantic: 0.5, feature: 0.5 }, color: '#AC6AFF', desc: 'Equal weight to meaning and keywords' },
  { label: 'Semantic', value: { semantic: 0.8, feature: 0.2 }, color: '#4687F1', desc: 'Prioritize contextual understanding' },
  { label: 'Feature', value: { semantic: 0.2, feature: 0.8 }, color: '#FF9C66', desc: 'Focus on exact keyword matches' },
];

const FEATURE_LABELS: Record<string, string> = {
  skills: 'Skills',
  experience: 'Experience',
  education: 'Education',
  title: 'Job Title',
  other: 'Other'
};

const RANKING_TOOLTIPS: Record<string, string> = {
  skills: 'How much to prioritize technical skills and competencies',
  experience: 'Weight given to years of experience and work history',
  education: 'Importance of educational background and degrees',
  title: 'How closely job titles should match',
  other: 'Weight for additional qualifications (certifications, languages, etc.)'
};

export const Sidebar: React.FC<SidebarProps> = ({
  isOpen,
  onToggle,
  sessions,
  activeSessionId,
  onSelectSession,
  onNewSession,
  onDeleteSession,
  width = 400
}) => {
  const [activeTab, setActiveTab] = useState<'sessions' | 'context'>('sessions');
  const [isJobSnapshotExpanded, setIsJobSnapshotExpanded] = useState(false);
  const [config, setConfig] = useState<any>({
    top_k: 5,
    scoring_weights: { semantic: 0.8, feature: 0.2 },
    feature_weights: { skills: 1.0, experience: 1.0, education: 1.0, title: 1.0, other: 1.0 },
    job_snapshot: null
  });

  useEffect(() => {
    const loadJobSnapshot = async () => {
      if (activeSessionId) {
        try {
          const { getSession } = await import('../api/client');
          const sessionData = await getSession(activeSessionId);
          if (sessionData?.job_snapshot) {
            setConfig((prev: any) => ({
              ...prev,
              job_snapshot: sessionData.job_snapshot
            }));
          }
        } catch (error) {
          console.error("Failed to load job snapshot", error);
        }
      }
    };
    loadJobSnapshot();
  }, [activeSessionId]);

  const handleConfigChange = async (key: string, value: any) => {
    const newConfig = { ...config, [key]: value };
    setConfig(newConfig);
    if (activeSessionId) {
      try {
        await updateSessionConfig(activeSessionId, { [key]: value });
      } catch (error) {
        console.error("Failed to update config", error);
      }
    }
  };

  const handleFeatureWeightChange = async (feature: string, value: number) => {
    const newWeights = { ...config.feature_weights, [feature]: value };
    handleConfigChange('feature_weights', newWeights);
  };

  return (
    <div
      className={clsx(
        "flex-shrink-0 bg-[#0E0C15] flex flex-col transition-all duration-300 ease-in-out font-sans",
        "fixed inset-y-0 left-0 z-50 md:relative md:translate-x-0",
        isOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0 md:!w-0 md:overflow-hidden"
      )}
      style={{ width: isOpen ? (window.innerWidth < 768 ? '100%' : width) : 0 }}
    >
      {/* Header */}
      <div className="h-16 flex items-center justify-between px-5">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg shadow-lg shadow-[#AC6AFF]/20 overflow-hidden">
            <img src="/hirex-logo.png" alt="HireX Logo" className="w-full h-full object-cover" />
          </div>
          <span className="text-white font-bold text-lg tracking-tight font-sora">
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#AC6AFF] to-[#4687F1]">Hire</span>X
          </span>
        </div>
        <button onClick={onToggle} className="md:hidden text-[#757185] hover:text-white transition-colors">
          <X size={20} />
        </button>
      </div>

      {/* Navigation Tabs */}
      <div className="px-5 mb-6">
        <div className="max-w-[460px] mx-auto w-full">
          <div className="flex p-1 bg-[#15131D] rounded-xl border border-[#252134]">
            <button
              onClick={() => setActiveTab('sessions')}
              className={clsx(
                "flex-1 py-2 text-[10px] font-bold uppercase tracking-wider rounded-lg transition-all duration-200",
                activeTab === 'sessions'
                  ? "bg-[#252134] text-white shadow-sm"
                  : "text-[#757185] hover:text-white"
              )}
            >
              Chats
            </button>
            <button
              onClick={() => setActiveTab('context')}
              className={clsx(
                "flex-1 py-2 text-[10px] font-bold uppercase tracking-wider rounded-lg transition-all duration-200",
                activeTab === 'context'
                  ? "bg-[#252134] text-white shadow-sm"
                  : "text-[#757185] hover:text-white"
              )}
            >
              Active Context
            </button>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-5 pb-5 scrollbar-thin scrollbar-thumb-[#252134]">
        <div className="max-w-[460px] mx-auto w-full">
          {activeTab === 'sessions' ? (
            <div className="space-y-4">
              <button
                onClick={onNewSession}
                className="w-full group flex items-center gap-2.5 px-3 py-2.5 bg-[#252134] hover:bg-[#2E2A3D] text-white rounded-xl transition-all border border-[#252134] hover:border-[#AC6AFF]/50"
              >
                <div className="bg-[#AC6AFF] rounded-lg p-0.5 group-hover:scale-110 transition-transform">
                  <Plus size={12} strokeWidth={3} className="text-white" />
                </div>
                <span className="text-xs font-bold">New Chat</span>
              </button>

              <div className="space-y-1.5">
                <div className="px-2 text-[10px] font-bold text-[#757185] uppercase tracking-wider mb-2">Recent Chats</div>
                {sessions.map((session) => (
                  <div
                    key={session.id}
                    className={clsx(
                      "group relative flex items-center gap-2.5 px-3 py-2.5 rounded-xl cursor-pointer transition-all duration-200 border",
                      activeSessionId === session.id
                        ? "bg-[#4687F1]/10 border-[#4687F1]/50 text-white"
                        : "bg-transparent border-transparent text-[#757185] hover:bg-[#15131D] hover:text-white"
                    )}
                    onClick={() => onSelectSession(session.id)}
                  >
                    <MessageSquare size={14} className={clsx(
                      "flex-shrink-0 transition-colors",
                      activeSessionId === session.id ? "text-[#4687F1]" : "text-[#757185] group-hover:text-white"
                    )} />
                    <div className="flex-1 min-w-0">
                      <div className="truncate text-xs font-medium">{session.label || "Untitled Session"}</div>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteSession(session.id);
                      }}
                      className="absolute right-2 p-1 text-[#757185] hover:text-[#FF9C66] hover:bg-[#FF9C66]/10 rounded-lg opacity-0 group-hover:opacity-100 transition-all"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              {/* Job Snapshot with Expander */}
              {config.job_snapshot && (
                <div className="relative overflow-hidden bg-gradient-to-br from-[#15131D] to-[#0E0C15] rounded-2xl p-4 border border-[#252134]">
                  <div className="absolute top-0 right-0 p-3 opacity-5">
                    <Briefcase size={60} />
                  </div>
                  <div className="relative z-10">
                    <div className="flex items-center justify-between mb-2">
                      <div className="text-[10px] font-bold text-[#AC6AFF] uppercase tracking-wider">Job Snapshot</div>
                      <button
                        onClick={() => setIsJobSnapshotExpanded(!isJobSnapshotExpanded)}
                        className="text-[#757185] hover:text-white transition-colors p-1 hover:bg-[#252134] rounded-lg"
                      >
                        {isJobSnapshotExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                      </button>
                    </div>
                    <div className="text-base font-bold text-white mb-1.5 font-sora">{config.job_snapshot.job_title || "No Title"}</div>
                    <div className="text-xs text-gray-300 mb-3">{config.job_snapshot.location}</div>

                    {isJobSnapshotExpanded && (
                      <div className="mt-4 space-y-3 animate-in slide-in-from-top-2 duration-200">
                        {config.job_snapshot.required_skills?.length > 0 && (
                          <div>
                            <div className="text-[10px] font-bold text-white uppercase tracking-wider mb-1.5">Required Skills</div>
                            <div className="flex flex-wrap gap-1.5">
                              {config.job_snapshot.required_skills.map((skill: string, i: number) => (
                                <span key={i} className="px-2 py-0.5 bg-[#252134] rounded-md text-[10px] text-white border border-[#AC6AFF]/30">{skill}</span>
                              ))}
                            </div>
                          </div>
                        )}
                        {config.job_snapshot.experience_level_years && (
                          <div>
                            <div className="text-[10px] font-bold text-white uppercase tracking-wider mb-1">Experience Required</div>
                            <div className="text-xs text-gray-300">{config.job_snapshot.experience_level_years}+ years</div>
                          </div>
                        )}
                        {config.job_snapshot.job_responsibilities?.length > 0 && (
                          <div>
                            <div className="text-[10px] font-bold text-white uppercase tracking-wider mb-1.5">Key Responsibilities</div>
                            <ul className="list-disc list-inside text-[10px] text-gray-300 space-y-0.5">
                              {config.job_snapshot.job_responsibilities.slice(0, 5).map((resp: string, i: number) => (
                                <li key={i} className="line-clamp-2">{resp}</li>
                              ))}
                              {config.job_snapshot.job_responsibilities.length > 5 && (
                                <li className="text-[#AC6AFF] italic">+{config.job_snapshot.job_responsibilities.length - 5} more...</li>
                              )}
                            </ul>
                          </div>
                        )}
                        {config.job_snapshot.education_requirements?.length > 0 && (
                          <div>
                            <div className="text-[10px] font-bold text-white uppercase tracking-wider mb-1.5">Education Requirements</div>
                            <ul className="list-disc list-inside text-[10px] text-gray-300 space-y-0.5">
                              {config.job_snapshot.education_requirements.map((edu: string, i: number) => (
                                <li key={i}>{edu}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {config.job_snapshot.preferred_qualifications?.length > 0 && (
                          <div>
                            <div className="text-[10px] font-bold text-white uppercase tracking-wider mb-1.5">Preferred Qualifications</div>
                            <ul className="list-disc list-inside text-[10px] text-gray-300 space-y-0.5">
                              {config.job_snapshot.preferred_qualifications.slice(0, 3).map((qual: string, i: number) => (
                                <li key={i} className="line-clamp-1">{qual}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {config.job_snapshot.certification_requirements?.length > 0 && (
                          <div>
                            <div className="text-[10px] font-bold text-white uppercase tracking-wider mb-1.5">Certifications</div>
                            <div className="flex flex-wrap gap-1.5">
                              {config.job_snapshot.certification_requirements.map((cert: string, i: number) => (
                                <span key={i} className="px-2 py-0.5 bg-[#252134] rounded-md text-[10px] text-[#4687F1] border border-[#4687F1]/30">{cert}</span>
                              ))}
                            </div>
                          </div>
                        )}
                        {config.job_snapshot.language_requirements?.length > 0 && (
                          <div>
                            <div className="text-[10px] font-bold text-white uppercase tracking-wider mb-1.5">Languages</div>
                            <div className="flex flex-wrap gap-1.5">
                              {config.job_snapshot.language_requirements.map((lang: string, i: number) => (
                                <span key={i} className="px-2 py-0.5 bg-[#252134] rounded-md text-[10px] text-[#FF9C66] border border-[#FF9C66]/30">{lang}</span>
                              ))}
                            </div>
                          </div>
                        )}
                        {config.job_snapshot.job_type && (
                          <div>
                            <div className="text-[10px] font-bold text-white uppercase tracking-wider mb-1">Employment Type</div>
                            <div className="text-xs text-gray-300 capitalize">{config.job_snapshot.job_type}</div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Search Config */}
              <div className="space-y-3">
                <div className="flex items-center gap-2.5 text-xs font-bold text-white uppercase tracking-wider">
                  <Search size={14} className="text-[#AC6AFF]" />
                  <span>Search Configuration</span>
                </div>

                <div className="bg-[#15131D] rounded-2xl p-4 border border-[#252134] space-y-4">
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <label className="text-xs font-semibold text-gray-300">Results Limit</label>
                      <span className="text-[10px] font-mono text-[#AC6AFF] bg-[#AC6AFF]/10 px-2 py-0.5 rounded-md">{config.top_k}</span>
                    </div>
                    <input
                      type="range"
                      min="1"
                      max="20"
                      value={config.top_k}
                      onChange={(e) => handleConfigChange('top_k', parseInt(e.target.value))}
                      className="w-full h-1 bg-[#252134] rounded-full appearance-none cursor-pointer accent-[#AC6AFF]"
                    />
                  </div>

                  <div className="space-y-2">
                    <div className="flex items-center justify-between mb-1.5">
                      <label className="text-xs font-bold text-white">Match Strategy</label>
                      <div className="relative group">
                        <HelpCircle size={11} className="text-[#757185] hover:text-white transition-colors cursor-help" />
                        <div className="absolute right-0 bottom-full mb-2 w-48 p-2.5 bg-[#0E0C15] border border-[#AC6AFF]/50 rounded-lg text-[10px] text-gray-300 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50 shadow-xl font-medium leading-relaxed">
                          Choose how to balance semantic understanding (context/meaning) vs. keyword matching (exact terms)
                        </div>
                      </div>
                    </div>
                    <div className="grid grid-cols-3 gap-1.5">
                      {SCORING_OPTIONS.map((opt) => (
                        <button
                          key={opt.label}
                          onClick={() => handleConfigChange('scoring_weights', opt.value)}
                          className={clsx(
                            "py-2 text-[10px] font-bold rounded-lg transition-all relative group",
                            JSON.stringify(config.scoring_weights) === JSON.stringify(opt.value)
                              ? "text-white shadow-lg"
                              : "text-gray-400 hover:text-white hover:bg-[#252134]"
                          )}
                          style={{
                            backgroundColor: JSON.stringify(config.scoring_weights) === JSON.stringify(opt.value) ? opt.color : undefined,
                            boxShadow: JSON.stringify(config.scoring_weights) === JSON.stringify(opt.value) ? `0 4px 14px 0 ${opt.color}40` : undefined
                          }}
                        >
                          {opt.label}
                          <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 w-40 p-2.5 bg-[#0E0C15] border border-[#AC6AFF]/50 rounded-lg text-[10px] text-gray-300 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50 shadow-xl whitespace-normal font-medium leading-relaxed">
                            {opt.desc}
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* Ranking Priorities */}
              <div className="space-y-3">
                <div className="flex items-center gap-2.5 text-xs font-bold text-white uppercase tracking-wider">
                  <Sliders size={14} className="text-[#4687F1]" />
                  <span>Ranking Priorities</span>
                  <div className="relative group ml-auto">
                    <HelpCircle size={11} className="text-[#757185] hover:text-white transition-colors cursor-help" />
                    <div className="absolute right-0 bottom-full mb-2 w-56 p-2.5 bg-[#0E0C15] border border-[#4687F1]/50 rounded-lg text-[10px] text-gray-300 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50 shadow-xl font-medium leading-relaxed">
                      Adjust the importance of different attributes when ranking candidates. Higher weights give more priority to that feature.
                    </div>
                  </div>
                </div>

                <div className="bg-[#15131D] rounded-2xl p-4 border border-[#252134] space-y-3.5">
                  {Object.entries(config.feature_weights).map(([feature, weight]) => {
                    const label = FEATURE_LABELS[feature] || feature;
                    const tooltip = RANKING_TOOLTIPS[feature] || '';
                    const currentOpt = WEIGHT_OPTIONS.find(opt => Math.abs((weight as number) - opt.value) < 0.1);
                    const currentLabel = currentOpt?.label || 'Custom';

                    return (
                      <div key={feature} className="space-y-1.5">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-1.5">
                            <span className="text-xs text-gray-200 capitalize font-medium">{label}</span>
                            <div className="relative group">
                              <HelpCircle size={9} className="text-[#757185] hover:text-white transition-colors cursor-help" />
                              <div className="absolute left-0 bottom-full mb-2 w-48 p-2.5 bg-[#0E0C15] border border-[#AC6AFF]/50 rounded-lg text-[10px] text-gray-300 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50 shadow-xl font-medium leading-relaxed">
                                {tooltip}
                              </div>
                            </div>
                          </div>
                          <span className="text-[9px] text-[#757185] font-mono">{currentLabel}</span>
                        </div>
                        <div className="flex gap-1.5">
                          {WEIGHT_OPTIONS.map((opt) => {
                            const isActive = Math.abs((weight as number) - opt.value) < 0.1;
                            return (
                              <button
                                key={opt.label}
                                onClick={() => handleFeatureWeightChange(feature, opt.value)}
                                className={clsx(
                                  "flex-1 py-1.5 text-[10px] font-bold rounded-lg border transition-all",
                                  isActive
                                    ? "text-white shadow-lg"
                                    : "bg-transparent border-[#252134] text-gray-400 hover:border-gray-500 hover:text-white"
                                )}
                                style={{
                                  backgroundColor: isActive ? opt.color : undefined,
                                  borderColor: isActive ? opt.color : undefined,
                                  boxShadow: isActive ? `0 4px 14px 0 ${opt.color}40` : undefined
                                }}
                              >
                                {opt.label}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* User Profile */}
      <div className="p-3 border-t border-[#252134]">
        <div className="flex items-center gap-2 p-2 rounded-lg hover:bg-[#15131D] transition-colors cursor-pointer border border-transparent hover:border-[#252134]">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-tr from-[#FF9C66] to-[#FF5E62] flex items-center justify-center text-white font-bold text-[9px] shadow-lg">
            RR
          </div>
          <div className="flex flex-col">
            <span className="text-[11px] text-white font-bold">Recruiter</span>
            <span className="text-[8px] text-[#757185] uppercase tracking-wide font-bold">Pro Plan</span>
          </div>
        </div>
      </div>
    </div>
  );
};
