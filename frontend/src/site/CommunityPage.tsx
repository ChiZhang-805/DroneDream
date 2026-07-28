import {
  Activity,
  ArrowLeft,
  ArrowUpRight,
  ChartNoAxesCombined,
  ChevronRight,
  Compass,
  Gauge,
  Heart,
  ImagePlus,
  MessageCircle,
  PenLine,
  Reply,
  Search,
  Send,
  Tag,
  Trash2,
  Upload,
  UserRound,
  Wind,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  type FormEvent,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import type { DroneDreamAccount } from "../features/auth/AuthContext";
import { supabaseClient } from "../features/auth/supabaseClient";
import {
  COMMUNITY_IMAGE_MAX_FILES,
  CommunityImageError,
  optimizeCommunityImage,
} from "./communityMedia";
import { useModalFocus } from "./useModalFocus";

type SiteLocale = "en" | "zh-CN";

interface CommunityPageProps {
  locale: SiteLocale;
  account: DroneDreamAccount | null;
  onRequireAccount: () => void;
}

interface CommunityTopic {
  id: string;
  author_id: string;
  author_name: string;
  title: string;
  body: string;
  tags: string[];
  image_urls: string[];
  created_at: string;
  comment_count: number;
  like_count: number;
  liked_by_viewer: boolean;
}

interface CommunityComment {
  id: string;
  topic_id: string;
  parent_id: string | null;
  parent_author_name: string | null;
  author_id: string;
  author_name: string;
  body: string;
  created_at: string;
  like_count: number;
  liked_by_viewer: boolean;
}

const TOPIC_PAGE_SIZE = 24;
const COMMENT_PAGE_SIZE = 100;

const tagOptions = {
  en: [
    "Simulation",
    "Optimizer",
    "Flight track",
    "PX4",
    "Failure analysis",
    "Evidence",
  ],
  "zh-CN": ["仿真问题", "调优算法", "飞行轨迹", "PX4 参数", "失败分析", "证据复查"],
} as const;

const communityContent = {
  en: {
    eyebrow: "DRONEDREAM COMMUNITY",
    title: "Share questions. Compare flight evidence.",
    mobileTitle: "Share flight evidence.",
    intro:
      "Search practical PX4 studies, publish reproducible findings, and improve decisions together.",
    newTopic: "Create a topic",
    signIn: "Sign in to publish",
    search: "Search topics, evidence, or tags",
    recent: "Recent topics",
    allTopics: "All topics",
    more: "More topics",
    back: "Back to recent topics",
    empty: "No topic matches this view. Start the first evidence-backed discussion.",
    loading: "Loading community topics…",
    unavailable: "The community connection is temporarily unavailable.",
    titleLabel: "Topic title",
    titlePlaceholder: "What should the community help you understand?",
    bodyLabel: "Evidence and context",
    bodyPlaceholder:
      "Describe the aircraft, route, parameters, observed result, evidence already checked, and the exact comparison you want the community to review.",
    tagsLabel: "Tags",
    customTag: "Add a custom tag",
    mediaLabel: "Images",
    mediaHint: "JPEG, PNG, or WebP · up to 4 images, optimized below 1 MiB each",
    mediaUnsupported: "Use a JPEG, PNG, or WebP image.",
    mediaSourceTooLarge: "Each source image must be 12 MiB or smaller.",
    mediaDecodeFailed: "One of the selected images could not be processed.",
    mediaOutputTooLarge: "One image could not be reduced below the upload limit.",
    preparingMedia: "Optimizing images…",
    publish: "Publish topic",
    publishing: "Publishing…",
    cancel: "Cancel",
    posted: "Published",
    owner: "Your topic",
    open: "Open discussion",
    comments: "Comments",
    commentPlaceholder: "Add a useful observation or a reproducible next step…",
    reply: "Reply",
    replyingTo: "Replying to",
    clearReply: "Cancel reply",
    sendComment: "Post comment",
    likes: "likes",
    loadMore: "Load more topics",
    loadMoreComments: "Load more comments",
    noComments: "No comments yet. Add the first evidence-based response.",
    signInAction: "Sign in to join the discussion",
    removeImage: "Remove image",
    deleteTopic: "Delete topic",
    deletingTopic: "Deleting topic…",
    deleteTopicConfirm: "Delete this topic and all of its comments? This cannot be undone.",
    close: "Close",
  },
  "zh-CN": {
    eyebrow: "DRONEDREAM 社区",
    title: "分享问题，比较飞行证据。",
    mobileTitle: "分享飞行证据。",
    intro: "检索真实的 PX4 研究、发表可复现的发现，并共同改进每一次工程判断。",
    newTopic: "创建话题",
    signIn: "登录后发表",
    search: "搜索话题、证据或标签",
    recent: "近期话题",
    allTopics: "全部话题",
    more: "查看更多",
    back: "返回近期话题",
    empty: "当前视图没有匹配的话题；你可以发起第一场有证据的讨论。",
    loading: "正在加载社区话题……",
    unavailable: "社区连接暂时不可用。",
    titleLabel: "话题标题",
    titlePlaceholder: "你希望社区帮助理解什么问题？",
    bodyLabel: "证据与背景",
    bodyPlaceholder: "请描述飞行器、轨迹、参数、观察结果、已经核对过的证据，以及希望社区进一步比较或判断的具体问题。",
    tagsLabel: "标签",
    customTag: "添加自定义标签",
    mediaLabel: "图片",
    mediaHint: "支持 JPEG、PNG 或 WebP；最多 4 张，自动优化至每张 1 MiB 以下",
    mediaUnsupported: "请选择 JPEG、PNG 或 WebP 图片。",
    mediaSourceTooLarge: "每张原始图片不得超过 12 MiB。",
    mediaDecodeFailed: "其中一张图片无法处理，请更换后重试。",
    mediaOutputTooLarge: "其中一张图片无法压缩到上传限制以内。",
    preparingMedia: "正在优化图片……",
    publish: "发表话题",
    publishing: "正在发表……",
    cancel: "取消",
    posted: "发布于",
    owner: "你的话题",
    open: "打开讨论",
    comments: "评论",
    commentPlaceholder: "补充一条有用的观察，或给出可复现的下一步……",
    reply: "回复",
    replyingTo: "正在回复",
    clearReply: "取消回复",
    sendComment: "发表评论",
    likes: "次点赞",
    loadMore: "加载更多话题",
    loadMoreComments: "加载更多评论",
    noComments: "还没有评论；你可以补充第一条基于证据的回复。",
    signInAction: "登录后参与讨论",
    removeImage: "移除图片",
    deleteTopic: "删除话题",
    deletingTopic: "正在删除话题……",
    deleteTopicConfirm: "确定删除这个话题及其全部评论吗？此操作无法撤销。",
    close: "关闭",
  },
} as const;

function dateLabel(locale: SiteLocale, value: string) {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

type TopicCoverTemplate = "analysis" | "comparison" | "route" | "wind" | "evidence";

interface TopicCoverPresentation {
  template: TopicCoverTemplate;
  kicker: string;
  emphasis: string;
  issue: string;
  icon: LucideIcon;
}

function topicCoverPresentation(
  topic: CommunityTopic,
  locale: SiteLocale,
): TopicCoverPresentation {
  const subject = `${topic.title} ${topic.body} ${topic.tags.join(" ")}`.toLocaleLowerCase(locale);
  const issue = new Intl.DateTimeFormat(locale, {
    month: "short",
    day: "2-digit",
  }).format(new Date(topic.created_at));
  const emphasis = topic.tags[0] ?? (locale === "zh-CN" ? "飞行调优" : "Flight tuning");

  if (/(wind|gust|风|抗风)/u.test(subject)) {
    return {
      template: "wind",
      kicker: locale === "zh-CN" ? "抗扰研究笔记" : "ROBUSTNESS NOTE",
      emphasis,
      issue,
      icon: Wind,
    };
  }
  if (/(versus|compare|comparison|bayes|cma|对比|比较|优化器)/u.test(subject)) {
    return {
      template: "comparison",
      kicker: locale === "zh-CN" ? "算法对照实验" : "METHOD COMPARISON",
      emphasis,
      issue,
      icon: ChartNoAxesCombined,
    };
  }
  if (/(route|track|waypoint|trajectory|轨迹|航线|航点)/u.test(subject)) {
    return {
      template: "route",
      kicker: locale === "zh-CN" ? "飞行轨迹研究" : "FLIGHT PATH STUDY",
      emphasis,
      issue,
      icon: Compass,
    };
  }
  if (/(fail|failure|overshoot|error|失败|超调|故障)/u.test(subject)) {
    return {
      template: "analysis",
      kicker: locale === "zh-CN" ? "问题诊断记录" : "DIAGNOSTIC LOG",
      emphasis,
      issue,
      icon: Activity,
    };
  }
  return {
    template: "evidence",
    kicker: locale === "zh-CN" ? "可复查飞行证据" : "FLIGHT EVIDENCE",
    emphasis,
    issue,
    icon: Gauge,
  };
}

function TopicCoverArtwork({
  topic,
  locale,
  dialog = false,
}: {
  topic: CommunityTopic;
  locale: SiteLocale;
  dialog?: boolean;
}) {
  const presentation = topicCoverPresentation(topic, locale);
  const Icon = presentation.icon;
  return (
    <div
      className={`community-cover-art is-${presentation.template}${dialog ? " is-dialog" : ""}`}
      data-template={presentation.template}
    >
      <span className="community-cover-shape is-primary" aria-hidden="true" />
      <span className="community-cover-shape is-secondary" aria-hidden="true" />
      <header>
        <Icon aria-hidden="true" />
        <span>{presentation.kicker}</span>
      </header>
      <strong>{topic.title}</strong>
      <p><span>#{presentation.emphasis}</span></p>
      <footer>
        <time dateTime={topic.created_at}>{presentation.issue}</time>
        <span>DRONEDREAM · 1.0</span>
      </footer>
    </div>
  );
}

export function CommunityPage({
  locale,
  account,
  onRequireAccount,
}: CommunityPageProps) {
  const copy = communityContent[locale];
  const presets = tagOptions[locale];
  const allTopicsView = new URLSearchParams(window.location.search).get("view") === "all";
  const [topics, setTopics] = useState<CommunityTopic[]>([]);
  const [comments, setComments] = useState<CommunityComment[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMoreTopics, setLoadingMoreTopics] = useState(false);
  const [hasMoreTopics, setHasMoreTopics] = useState(false);
  const [commentsLoading, setCommentsLoading] = useState(false);
  const [hasMoreComments, setHasMoreComments] = useState(false);
  const [feedError, setFeedError] = useState<string | null>(null);
  const [composerError, setComposerError] = useState<string | null>(null);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [settledQuery, setSettledQuery] = useState("");
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [composerOpen, setComposerOpen] = useState(false);
  const [selectedTopic, setSelectedTopic] = useState<CommunityTopic | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [customTag, setCustomTag] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [preparingMedia, setPreparingMedia] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [deletingTopicId, setDeletingTopicId] = useState<string | null>(null);
  const [commentBody, setCommentBody] = useState("");
  const [replyTo, setReplyTo] = useState<CommunityComment | null>(null);
  const composerRef = useRef<HTMLFormElement>(null);
  const composerTitleRef = useRef<HTMLInputElement>(null);
  const topicDialogRef = useRef<HTMLElement>(null);
  const topicCloseRef = useRef<HTMLButtonElement>(null);
  const captureComposerTrigger = useModalFocus({
    open: composerOpen,
    dialogRef: composerRef,
    initialFocusRef: composerTitleRef,
    onClose: () => setComposerOpen(false),
  });
  const captureTopicTrigger = useModalFocus({
    open: Boolean(selectedTopic),
    dialogRef: topicDialogRef,
    initialFocusRef: topicCloseRef,
    onClose: () => setSelectedTopic(null),
  });

  const loadTopics = useCallback(async (offset = 0, append = false) => {
    if (!supabaseClient) {
      setLoading(false);
      setFeedError(copy.unavailable);
      return;
    }
    if (append) setLoadingMoreTopics(true);
    else setLoading(true);
    setFeedError(null);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 8000);
    try {
      const { data, error: requestError } = await supabaseClient
        .rpc("community_list_topics", {
          p_search: settledQuery.trim() || null,
          p_tag: activeTag,
          p_offset: offset,
          p_limit: TOPIC_PAGE_SIZE + 1,
        })
        .abortSignal(controller.signal);
      if (requestError) throw requestError;
      const page = ((data ?? []) as CommunityTopic[]).map((topic) => ({
        ...topic,
        comment_count: Number(topic.comment_count),
        like_count: Number(topic.like_count),
      }));
      const boundedPage = page.slice(0, TOPIC_PAGE_SIZE);
      setHasMoreTopics(page.length > TOPIC_PAGE_SIZE);
      setTopics((current) => append ? [...current, ...boundedPage] : boundedPage);
    } catch {
      setFeedError(copy.unavailable);
    } finally {
      window.clearTimeout(timeout);
      if (append) setLoadingMoreTopics(false);
      else setLoading(false);
    }
  }, [activeTag, copy.unavailable, settledQuery]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      setSettledQuery(query);
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [query]);

  useEffect(() => {
    void loadTopics();
  }, [loadTopics]);

  const loadComments = useCallback(async (
    topicId: string,
    offset = 0,
    append = false,
  ) => {
    if (!supabaseClient) return;
    setCommentsLoading(true);
    setDialogError(null);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 8000);
    try {
      const { data, error: requestError } = await supabaseClient
        .rpc("community_list_comments", {
          p_topic_id: topicId,
          p_offset: offset,
          p_limit: COMMENT_PAGE_SIZE + 1,
        })
        .abortSignal(controller.signal);
      if (requestError) throw requestError;
      const page = ((data ?? []) as CommunityComment[]).map((comment) => ({
        ...comment,
        like_count: Number(comment.like_count),
      }));
      const boundedPage = page.slice(0, COMMENT_PAGE_SIZE);
      setHasMoreComments(page.length > COMMENT_PAGE_SIZE);
      setComments((current) => append ? [...current, ...boundedPage] : boundedPage);
    } catch {
      setDialogError(copy.unavailable);
    } finally {
      window.clearTimeout(timeout);
      setCommentsLoading(false);
    }
  }, [copy.unavailable]);

  const visibleTopics = allTopicsView ? topics : topics.slice(0, 5);

  const openTopic = (topic: CommunityTopic) => {
    captureTopicTrigger();
    setDialogError(null);
    setSelectedTopic(topic);
    setComments([]);
    setHasMoreComments(false);
    void loadComments(topic.id);
  };

  const startTopic = () => {
    if (!account) {
      onRequireAccount();
      return;
    }
    captureComposerTrigger();
    setComposerError(null);
    setComposerOpen(true);
  };

  const addCustomTag = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.nativeEvent.isComposing || (event.key !== "Enter" && event.key !== ",")) return;
    event.preventDefault();
    const value = customTag.trim().replace(/^#/u, "").slice(0, 24);
    if (value) {
      setTags((current) =>
        !current.includes(value) && current.length < 5
          ? [...current, value]
          : current
      );
    }
    setCustomTag("");
  };

  const selectImages = async (selected: File[]) => {
    setPreparingMedia(true);
    setComposerError(null);
    try {
      const optimized: File[] = [];
      for (const file of selected.slice(0, COMMUNITY_IMAGE_MAX_FILES)) {
        optimized.push(await optimizeCommunityImage(file));
      }
      setFiles(optimized);
    } catch (mediaError) {
      if (mediaError instanceof CommunityImageError) {
        const message = {
          "unsupported-type": copy.mediaUnsupported,
          "source-too-large": copy.mediaSourceTooLarge,
          "decode-failed": copy.mediaDecodeFailed,
          "output-too-large": copy.mediaOutputTooLarge,
        }[mediaError.code];
        setComposerError(message);
      } else {
        setComposerError(copy.mediaDecodeFailed);
      }
    } finally {
      setPreparingMedia(false);
    }
  };

  const removeUploadedImages = async (paths: string[]) => {
    if (!supabaseClient || paths.length === 0) return;
    const { error: removeError } = await supabaseClient.storage
      .from("community-media")
      .remove(paths);
    if (removeError) {
      console.warn("Failed to remove unpublished community media.", removeError);
    }
  };

  const uploadImages = async () => {
    if (!account || !supabaseClient || files.length === 0) {
      return { urls: [] as string[], paths: [] as string[] };
    }
    const urls: string[] = [];
    const paths: string[] = [];
    try {
      for (const [index, file] of files.entries()) {
        const path = `${account.id}/${crypto.randomUUID()}-${index}.webp`;
        const { error: uploadError } = await supabaseClient.storage
          .from("community-media")
          .upload(path, file, {
            cacheControl: "31536000",
            contentType: "image/webp",
            upsert: false,
          });
        if (uploadError) throw uploadError;
        paths.push(path);
        const { data } = supabaseClient.storage.from("community-media").getPublicUrl(path);
        urls.push(data.publicUrl);
      }
      return { urls, paths };
    } catch (uploadError) {
      await removeUploadedImages(paths);
      throw uploadError;
    }
  };

  const publish = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!account || !supabaseClient || publishing) return;
    setPublishing(true);
    setComposerError(null);
    let uploadedPaths: string[] = [];
    try {
      const uploaded = await uploadImages();
      uploadedPaths = uploaded.paths;
      const { error: requestError } = await supabaseClient.from("community_topics").insert({
        author_id: account.id,
        author_name: account.displayName,
        title: title.trim(),
        body: body.trim(),
        tags,
        image_urls: uploaded.urls,
      });
      if (requestError) throw requestError;
      setTitle("");
      setBody("");
      setTags([]);
      setFiles([]);
      setComposerOpen(false);
      await loadTopics();
    } catch (requestError) {
      await removeUploadedImages(uploadedPaths);
      setComposerError(
        requestError instanceof Error ? requestError.message : copy.unavailable,
      );
    } finally {
      setPublishing(false);
    }
  };

  const deleteTopic = async (topic: CommunityTopic) => {
    if (
      !account ||
      account.id !== topic.author_id ||
      !supabaseClient ||
      deletingTopicId
    ) {
      return;
    }
    if (!window.confirm(copy.deleteTopicConfirm)) return;

    setDeletingTopicId(topic.id);
    if (selectedTopic?.id === topic.id) setDialogError(null);
    else setFeedError(null);
    try {
      const { error: requestError } = await supabaseClient
        .from("community_topics")
        .delete()
        .eq("id", topic.id)
        .eq("author_id", account.id);
      if (requestError) throw requestError;

      setTopics((current) =>
        current.filter((candidate) => candidate.id !== topic.id)
      );
      setSelectedTopic((current) =>
        current?.id === topic.id ? null : current
      );

      const mediaPrefix = "/storage/v1/object/public/community-media/";
      const mediaPaths = topic.image_urls.flatMap((url) => {
        const marker = url.indexOf(mediaPrefix);
        if (marker < 0) return [];
        const path = decodeURIComponent(url.slice(marker + mediaPrefix.length));
        return path.startsWith(`${account.id}/`) ? [path] : [];
      });
      await removeUploadedImages(mediaPaths);
    } catch (requestError) {
      const message = requestError instanceof Error
        ? requestError.message
        : copy.unavailable;
      if (selectedTopic?.id === topic.id) setDialogError(message);
      else setFeedError(message);
    } finally {
      setDeletingTopicId(null);
    }
  };

  const toggleTopicLike = async (topicId: string) => {
    if (!account || !supabaseClient) {
      onRequireAccount();
      return;
    }
    const topic = topics.find((candidate) => candidate.id === topicId)
      ?? (selectedTopic?.id === topicId ? selectedTopic : null);
    if (!topic) return;
    if (selectedTopic?.id === topicId) setDialogError(null);
    else setFeedError(null);
    const liked = topic.liked_by_viewer;
    const { error: requestError } = liked
      ? await supabaseClient
        .from("community_topic_likes")
        .delete()
        .eq("topic_id", topicId)
        .eq("user_id", account.id)
      : await supabaseClient
        .from("community_topic_likes")
        .insert({ topic_id: topicId, user_id: account.id });
    if (requestError) {
      if (selectedTopic?.id === topicId) setDialogError(requestError.message);
      else setFeedError(requestError.message);
      return;
    }
    const updateTopic = (candidate: CommunityTopic): CommunityTopic =>
      candidate.id === topicId
        ? {
            ...candidate,
            liked_by_viewer: !liked,
            like_count: Math.max(0, candidate.like_count + (liked ? -1 : 1)),
          }
        : candidate;
    setTopics((current) => current.map(updateTopic));
    setSelectedTopic((current) => current ? updateTopic(current) : current);
  };

  const toggleCommentLike = async (commentId: string) => {
    if (!account || !supabaseClient) {
      onRequireAccount();
      return;
    }
    const comment = comments.find((candidate) => candidate.id === commentId);
    if (!comment) return;
    setDialogError(null);
    const liked = comment.liked_by_viewer;
    const { error: requestError } = liked
      ? await supabaseClient
        .from("community_comment_likes")
        .delete()
        .eq("comment_id", commentId)
        .eq("user_id", account.id)
      : await supabaseClient
        .from("community_comment_likes")
        .insert({ comment_id: commentId, user_id: account.id });
    if (requestError) {
      setDialogError(requestError.message);
      return;
    }
    setComments((current) =>
      current.map((candidate) =>
        candidate.id === commentId
          ? {
              ...candidate,
              liked_by_viewer: !liked,
              like_count: Math.max(0, candidate.like_count + (liked ? -1 : 1)),
            }
          : candidate
      )
    );
  };

  const publishComment = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!account || !selectedTopic || !supabaseClient || !commentBody.trim()) return;
    setDialogError(null);
    const { error: requestError } = await supabaseClient.from("community_comments").insert({
      topic_id: selectedTopic.id,
      parent_id: replyTo?.id ?? null,
      author_id: account.id,
      author_name: account.displayName,
      body: commentBody.trim(),
    });
    if (requestError) {
      setDialogError(requestError.message);
      return;
    }
    setCommentBody("");
    setReplyTo(null);
    const updateTopic = (topic: CommunityTopic): CommunityTopic =>
      topic.id === selectedTopic.id
        ? { ...topic, comment_count: topic.comment_count + 1 }
        : topic;
    setTopics((current) => current.map(updateTopic));
    setSelectedTopic((current) => current ? updateTopic(current) : current);
    await loadComments(selectedTopic.id);
  };

  return (
    <div className={`site-portal community-page${allTopicsView ? " is-all-topics" : ""}`}>
      <header className="community-hero">
        <div>
          <p className="site-eyebrow">{copy.eyebrow}</p>
          <h1 aria-label={allTopicsView ? copy.allTopics : copy.title}>
            {allTopicsView ? copy.allTopics : (
              <>
                <span aria-hidden="true" className="portal-title-desktop">{copy.title}</span>
                <span aria-hidden="true" className="portal-title-mobile">{copy.mobileTitle}</span>
              </>
            )}
          </h1>
          <p>{copy.intro}</p>
        </div>
        <button type="button" onClick={startTopic}>
          <PenLine aria-hidden="true" />
          {account ? copy.newTopic : copy.signIn}
        </button>
      </header>

      <section className="community-feed" aria-labelledby="community-feed-heading">
        <header className="community-feed-heading">
          <div>
            {allTopicsView ? <Search aria-hidden="true" /> : <MessageCircle aria-hidden="true" />}
            <h2 id="community-feed-heading">
              {allTopicsView ? copy.allTopics : copy.recent}
            </h2>
          </div>
          <label className="community-search">
            <Search aria-hidden="true" />
            <input
              type="search"
              aria-label={copy.search}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={copy.search}
            />
          </label>
        </header>

        <div className="community-tag-filter" role="group" aria-label={copy.tagsLabel}>
          {presets.map((tagName) => (
            <button
              key={tagName}
              type="button"
              className={activeTag === tagName ? "is-active" : ""}
              aria-pressed={activeTag === tagName}
              onClick={() => setActiveTag(activeTag === tagName ? null : tagName)}
            >
              #{tagName}
            </button>
          ))}
        </div>

        {loading ? <p role="status">{copy.loading}</p> : null}

        {!loading && feedError ? (
          <p className="community-state is-error" role="alert">{feedError}</p>
        ) : null}

        {!loading && !feedError && visibleTopics.length === 0 ? (
          <p className="community-state" role="status">{copy.empty}</p>
        ) : null}

        <div className="community-topic-grid">
          {visibleTopics.map((topic) => {
            const liked = Boolean(account && topic.liked_by_viewer);
            return (
              <article key={topic.id}>
                <button
                  type="button"
                  className="community-topic-cover"
                  onClick={() => openTopic(topic)}
                  aria-label={`${copy.open}: ${topic.title}`}
                >
                  {topic.image_urls[0] ? (
                    <img
                      src={topic.image_urls[0]}
                      alt=""
                      loading="lazy"
                      decoding="async"
                    />
                  ) : (
                    <TopicCoverArtwork topic={topic} locale={locale} />
                  )}
                </button>
                <div className="community-topic-card-body">
                  <div className="community-topic-author">
                    <span><UserRound aria-hidden="true" /></span>
                    <div>
                      <strong>{topic.author_name}</strong>
                      <time dateTime={topic.created_at}>{dateLabel(locale, topic.created_at)}</time>
                    </div>
                    {account?.id === topic.author_id ? <em>{copy.owner}</em> : null}
                  </div>
                  <h3>{topic.title}</h3>
                  <p>{topic.body}</p>
                  <div className="community-topic-tags">
                    {topic.tags.slice(0, 3).map((tagName) => (
                      <span key={tagName}>#{tagName}</span>
                    ))}
                  </div>
                  <footer>
                    <button
                      type="button"
                      className={liked ? "is-liked" : ""}
                      aria-label={`${topic.like_count} ${copy.likes}`}
                      aria-pressed={liked}
                      onClick={() => void toggleTopicLike(topic.id)}
                    >
                      <Heart aria-hidden="true" />
                      {topic.like_count}
                    </button>
                    <button
                      type="button"
                      aria-label={`${topic.comment_count} ${copy.comments}`}
                      onClick={() => openTopic(topic)}
                    >
                      <MessageCircle aria-hidden="true" />
                      {topic.comment_count}
                    </button>
                    {account?.id === topic.author_id ? (
                      <button
                        type="button"
                        className="community-topic-delete"
                        disabled={deletingTopicId === topic.id}
                        onClick={() => void deleteTopic(topic)}
                        aria-label={copy.deleteTopic}
                        title={copy.deleteTopic}
                      >
                        <Trash2 aria-hidden="true" />
                      </button>
                    ) : null}
                    <button type="button" onClick={() => openTopic(topic)}>
                      {copy.open}
                      <ArrowUpRight aria-hidden="true" />
                    </button>
                  </footer>
                </div>
              </article>
            );
          })}
        </div>

        {!loading && !feedError && allTopicsView && hasMoreTopics ? (
          <button
            type="button"
            className="community-more"
            disabled={loadingMoreTopics}
            onClick={() => void loadTopics(topics.length, true)}
          >
            {copy.loadMore}
            <ChevronRight aria-hidden="true" />
          </button>
        ) : null}
        {!loading
          && !feedError
          && (allTopicsView || visibleTopics.length > 0)
          && (!allTopicsView || !hasMoreTopics) ? (
          <a
            className="community-more"
            href={allTopicsView ? "/community/" : "/community/?view=all"}
          >
            {allTopicsView ? (
              <><ArrowLeft aria-hidden="true" />{copy.back}</>
            ) : (
              <>{copy.more}<ChevronRight aria-hidden="true" /></>
            )}
          </a>
        ) : null}
      </section>

      {composerOpen && account ? (
        <div
          className="community-modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setComposerOpen(false);
          }}
        >
          <form
            ref={composerRef}
            className="community-composer"
            onSubmit={(event) => void publish(event)}
            role="dialog"
            aria-modal="true"
            aria-labelledby="community-composer-title"
            tabIndex={-1}
          >
            <header>
              <div>
                <PenLine aria-hidden="true" />
                <h2 id="community-composer-title">{copy.newTopic}</h2>
              </div>
              <button type="button" onClick={() => setComposerOpen(false)} aria-label={copy.close}>
                <X aria-hidden="true" />
              </button>
            </header>
            <label>
              <span>{copy.titleLabel}</span>
              <input
                ref={composerTitleRef}
                required
                maxLength={120}
                value={title}
                placeholder={copy.titlePlaceholder}
                onChange={(event) => setTitle(event.target.value)}
              />
            </label>
            <label>
              <span>{copy.bodyLabel}</span>
              <textarea
                required
                minLength={12}
                maxLength={4000}
                value={body}
                placeholder={copy.bodyPlaceholder}
                onChange={(event) => setBody(event.target.value)}
              />
            </label>
            <fieldset>
              <legend><Tag aria-hidden="true" />{copy.tagsLabel}</legend>
              <div className="community-composer-tags">
                {presets.map((tagName) => (
                  <button
                    key={tagName}
                    type="button"
                    className={tags.includes(tagName) ? "is-active" : ""}
                    aria-pressed={tags.includes(tagName)}
                    onClick={() =>
                      setTags(
                        tags.includes(tagName)
                          ? tags.filter((value) => value !== tagName)
                          : tags.length < 5
                            ? [...tags, tagName]
                            : tags,
                      )
                    }
                  >
                    #{tagName}
                  </button>
                ))}
                {tags
                  .filter((tagName) =>
                    !presets.some((preset) => preset === tagName)
                  )
                  .map((tagName) => (
                    <button
                      key={tagName}
                      type="button"
                      className="is-active"
                      aria-pressed="true"
                      onClick={() =>
                        setTags((current) =>
                          current.filter((value) => value !== tagName)
                        )
                      }
                    >
                      #{tagName}
                    </button>
                  ))}
                <input
                  aria-label={copy.customTag}
                  value={customTag}
                  onChange={(event) => setCustomTag(event.target.value)}
                  onKeyDown={addCustomTag}
                  placeholder={copy.customTag}
                />
              </div>
            </fieldset>
            <fieldset>
              <legend><ImagePlus aria-hidden="true" />{copy.mediaLabel}</legend>
              <label className="community-file-picker">
                <Upload aria-hidden="true" />
                <span>{preparingMedia ? copy.preparingMedia : copy.mediaHint}</span>
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  multiple
                  disabled={preparingMedia || publishing}
                  onChange={(event) => {
                    const selected = Array.from(event.target.files ?? []);
                    event.target.value = "";
                    void selectImages(selected);
                  }}
                />
              </label>
              {files.length ? (
                <div className="community-file-list">
                  {files.map((file) => (
                    <span key={`${file.name}-${file.lastModified}`}>
                      {file.name}
                      <button
                        type="button"
                        aria-label={`${copy.removeImage}: ${file.name}`}
                        onClick={() => setFiles(files.filter((candidate) => candidate !== file))}
                      >
                        <X aria-hidden="true" />
                      </button>
                    </span>
                  ))}
                </div>
              ) : null}
            </fieldset>
            {composerError ? (
              <p className="community-form-error" role="alert">{composerError}</p>
            ) : null}
            <footer>
              <button
                type="button"
                className="community-composer-cancel"
                onClick={() => setComposerOpen(false)}
              >
                {copy.cancel}
              </button>
              <button
                type="submit"
                disabled={
                  publishing ||
                  preparingMedia ||
                  !title.trim() ||
                  !body.trim()
                }
              >
                <Send aria-hidden="true" />
                {publishing ? copy.publishing : copy.publish}
              </button>
            </footer>
          </form>
        </div>
      ) : null}

      {selectedTopic ? (
        <div
          className="community-modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setSelectedTopic(null);
          }}
        >
          <section
            ref={topicDialogRef}
            className="community-topic-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="community-topic-title"
            tabIndex={-1}
          >
            <button
              ref={topicCloseRef}
              type="button"
              className="community-dialog-close"
              onClick={() => setSelectedTopic(null)}
              aria-label={copy.close}
            >
              <X aria-hidden="true" />
            </button>
            <div className="community-topic-dialog-visual">
              {selectedTopic.image_urls.length ? (
                selectedTopic.image_urls.map((url) => (
                  <img
                    key={url}
                    src={url}
                    alt=""
                    loading="lazy"
                    decoding="async"
                  />
                ))
              ) : (
                <TopicCoverArtwork topic={selectedTopic} locale={locale} dialog />
              )}
            </div>
            <div className="community-topic-dialog-content">
              <header>
                <div className="community-topic-author">
                  <span><UserRound aria-hidden="true" /></span>
                  <div>
                    <strong>{selectedTopic.author_name}</strong>
                    <time dateTime={selectedTopic.created_at}>
                      {dateLabel(locale, selectedTopic.created_at)}
                    </time>
                  </div>
                </div>
                <h2 id="community-topic-title">{selectedTopic.title}</h2>
                <p>{selectedTopic.body}</p>
                <div className="community-topic-tags">
                  {selectedTopic.tags.map((tagName) => (
                    <span key={tagName}>#{tagName}</span>
                  ))}
                </div>
                <div className="community-topic-dialog-actions">
                  <button
                    type="button"
                    className={
                      account && selectedTopic.liked_by_viewer ? "is-liked" : ""
                    }
                    aria-pressed={Boolean(account && selectedTopic.liked_by_viewer)}
                    onClick={() => void toggleTopicLike(selectedTopic.id)}
                  >
                    <Heart aria-hidden="true" />
                    {selectedTopic.like_count} {copy.likes}
                  </button>
                  {account?.id === selectedTopic.author_id ? (
                    <button
                      type="button"
                      className="community-topic-delete"
                      disabled={deletingTopicId === selectedTopic.id}
                      onClick={() => void deleteTopic(selectedTopic)}
                    >
                      <Trash2 aria-hidden="true" />
                      {deletingTopicId === selectedTopic.id
                        ? copy.deletingTopic
                        : copy.deleteTopic}
                    </button>
                  ) : null}
                </div>
              </header>
              {dialogError ? (
                <p className="community-form-error" role="alert">{dialogError}</p>
              ) : null}
              <div className="community-comment-list">
                <h3>{copy.comments}</h3>
                {commentsLoading && comments.length === 0 ? (
                  <p role="status">{copy.loading}</p>
                ) : null}
                {!commentsLoading && comments.length === 0 ? (
                  <p className="community-no-comments">{copy.noComments}</p>
                ) : null}
                {comments.map((comment) => {
                  const liked = Boolean(account && comment.liked_by_viewer);
                  return (
                    <article key={comment.id} className={comment.parent_id ? "is-reply" : ""}>
                      <header>
                        <strong>{comment.author_name}</strong>
                        <time dateTime={comment.created_at}>
                          {dateLabel(locale, comment.created_at)}
                        </time>
                      </header>
                      {comment.parent_author_name
                        ? <small>@{comment.parent_author_name}</small>
                        : null}
                      <p>{comment.body}</p>
                      <footer>
                        <button
                          type="button"
                          className={liked ? "is-liked" : ""}
                          aria-label={`${comment.like_count} ${copy.likes}`}
                          aria-pressed={liked}
                          onClick={() => void toggleCommentLike(comment.id)}
                        >
                          <Heart aria-hidden="true" />{comment.like_count}
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            if (!account) onRequireAccount();
                            else setReplyTo(comment);
                          }}
                        >
                          <Reply aria-hidden="true" />{copy.reply}
                        </button>
                      </footer>
                    </article>
                  );
                })}
                {hasMoreComments ? (
                  <button
                    type="button"
                    className="community-more"
                    disabled={commentsLoading}
                    onClick={() =>
                      void loadComments(selectedTopic.id, comments.length, true)
                    }
                  >
                    {copy.loadMoreComments}
                    <ChevronRight aria-hidden="true" />
                  </button>
                ) : null}
              </div>
              {account ? (
                <form
                  className="community-comment-form"
                  onSubmit={(event) => void publishComment(event)}
                >
                  {replyTo ? (
                    <div>
                      {copy.replyingTo} <strong>{replyTo.author_name}</strong>
                      <button type="button" onClick={() => setReplyTo(null)}>
                        {copy.clearReply}
                      </button>
                    </div>
                  ) : null}
                  <textarea
                    aria-label={copy.commentPlaceholder}
                    required
                    maxLength={2000}
                    value={commentBody}
                    onChange={(event) => setCommentBody(event.target.value)}
                    placeholder={copy.commentPlaceholder}
                  />
                  <button type="submit" disabled={!commentBody.trim()}>
                    <Send aria-hidden="true" />
                    <span className="site-sr-only">{copy.sendComment}</span>
                  </button>
                </form>
              ) : (
                <button
                  type="button"
                  className="community-sign-in-action"
                  onClick={onRequireAccount}
                >
                  {copy.signInAction}
                </button>
              )}
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
