import { useEffect, useMemo, useRef, useState } from "react";

import LoadingOverlay from "../../components/creation/LoadingOverlay";
import {
  createCrawlActivityDisplay,
  normalizeCrawlActivityFeed,
} from "../../utils/accountReport";

const STATUS_DISPLAY_MS = 2000;

function activityKey(activity, index) {
  if (Number.isFinite(activity.sequence)) return `sequence:${activity.sequence}`;
  return [
    activity.platform,
    activity.action,
    activity.status,
    activity.subject,
    activity.contentTitle,
    index,
  ].join(":");
}

export default function AccountReportLoadingOverlay({ workflow, reportView }) {
  const workflowId = workflow?.id || "starting";
  const activities = useMemo(() => normalizeCrawlActivityFeed(workflow), [workflow]);
  const queueRef = useRef([]);
  const seenRef = useRef(new Set());
  const [currentActivity, setCurrentActivity] = useState(null);

  useEffect(() => {
    queueRef.current = [];
    seenRef.current = new Set();
    setCurrentActivity(null);
  }, [workflowId]);

  useEffect(() => {
    activities.forEach((activity, index) => {
      const key = activityKey(activity, index);
      if (seenRef.current.has(key)) return;
      seenRef.current.add(key);
      queueRef.current.push(activity);
    });
    setCurrentActivity((current) => current || queueRef.current.shift() || null);
  }, [activities]);

  useEffect(() => {
    if (!currentActivity) return undefined;
    const timer = window.setTimeout(() => {
      setCurrentActivity(queueRef.current.shift() || null);
    }, STATUS_DISPLAY_MS);
    return () => window.clearTimeout(timer);
  }, [currentActivity]);

  const backendStatus = currentActivity
    ? createCrawlActivityDisplay(currentActivity).summary
    : reportView.stageLabel;

  if (reportView.hasPublishedReport || reportView.visibleCompletedSections.length > 0) {
    const progressVerb = reportView.hasPublishedReport ? "已更新" : "已展示";
    return (
      <section className="report-progress-banner" aria-busy="true" aria-live="polite">
        <span className="report-progress-banner-spinner" aria-hidden="true">✦</span>
        <div>
          <strong>
            正在生成账号报告 · {progressVerb} {reportView.visibleCompletedSections.length}/{reportView.visibleSectionsTotal} 个板块
          </strong>
          <small>{backendStatus || "其余板块生成完成后会自动展示"}</small>
        </div>
      </section>
    );
  }

  return (
    <LoadingOverlay
      message="正在生成账号报告"
      statusMessage="预计十分钟左右完成"
      subMessage={backendStatus || undefined}
      showProgress={false}
      embedded
    />
  );
}
