import {
  ArrowLeft,
  ArrowUpRight,
  Camera,
  ChevronRight,
  Heart,
  ImagePlus,
  MessageCircle,
  PenLine,
  Reply,
  Search,
  Send,
  Tag,
  Upload,
  UserRound,
  X,
} from "lucide-react";
import {
  type FormEvent,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import type { DroneDreamAccount } from "../features/auth/AuthContext";
import { supabaseClient } from "../features/auth/supabaseClient";

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
}

interface CommunityComment {
  id: string;
  topic_id: string;
  parent_id: string | null;
  author_id: string;
  author_name: string;
  body: string;
  created_at: string;
}

interface TopicLike {
  topic_id: string;
  user_id: string;
}

interface CommentLike {
  comment_id: string;
  user_id: string;
}

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
    starterTitle: "Start with a reproducible engineering question.",
    starterItems: [
      ["Describe the flight", "Name the vehicle, route, controller parameters, and the result you expected."],
      ["Attach the evidence", "Add screenshots, logs, plots, seeds, or exact settings that make the result inspectable."],
      ["Ask for a decision", "State the comparison, diagnosis, or next experiment you want the community to examine."],
    ],
    loading: "Loading community topics…",
    unavailable: "The community connection is temporarily unavailable.",
    titleLabel: "Topic title",
    titlePlaceholder: "What should the community help you understand?",
    bodyLabel: "Evidence and context",
    bodyPlaceholder:
      "Describe the aircraft, route, parameters, observed result, and the evidence already checked.",
    tagsLabel: "Tags",
    customTag: "Add a custom tag",
    mediaLabel: "Images",
    mediaHint: "JPEG, PNG, WebP, or GIF · up to 8 MiB each",
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
    noComments: "No comments yet. Add the first evidence-based response.",
    signInAction: "Sign in to join the discussion",
    removeImage: "Remove image",
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
    starterTitle: "从一个可复现的工程问题开始。",
    starterItems: [
      ["说明飞行任务", "写明飞行器、轨迹、控制参数，以及原本希望得到的结果。"],
      ["附上实验依据", "添加截图、日志、曲线、随机种子或完整设置，方便他人核对。"],
      ["提出判断问题", "明确希望社区比较、诊断或继续验证的下一项实验。"],
    ],
    loading: "正在加载社区话题……",
    unavailable: "社区连接暂时不可用。",
    titleLabel: "话题标题",
    titlePlaceholder: "你希望社区帮助理解什么问题？",
    bodyLabel: "证据与背景",
    bodyPlaceholder: "请描述飞行器、轨迹、参数、观察结果，以及已经核对过的证据。",
    tagsLabel: "标签",
    customTag: "添加自定义标签",
    mediaLabel: "图片",
    mediaHint: "支持 JPEG、PNG、WebP 或 GIF；每张不超过 8 MiB",
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
    noComments: "还没有评论；你可以补充第一条基于证据的回复。",
    signInAction: "登录后参与讨论",
    removeImage: "移除图片",
    close: "关闭",
  },
} as const;

function dateLabel(locale: SiteLocale, value: string) {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function fileExtension(file: File) {
  const extension = file.name.split(".").pop()?.toLowerCase();
  return extension && /^[a-z0-9]+$/u.test(extension) ? extension : "jpg";
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
  const [topicLikes, setTopicLikes] = useState<TopicLike[]>([]);
  const [commentLikes, setCommentLikes] = useState<CommentLike[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [composerOpen, setComposerOpen] = useState(false);
  const [selectedTopic, setSelectedTopic] = useState<CommunityTopic | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [customTag, setCustomTag] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [publishing, setPublishing] = useState(false);
  const [commentBody, setCommentBody] = useState("");
  const [replyTo, setReplyTo] = useState<CommunityComment | null>(null);

  const loadCommunity = useCallback(async () => {
    if (!supabaseClient) {
      setLoading(false);
      setError(copy.unavailable);
      return;
    }
    setLoading(true);
    setError(null);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 8000);
    try {
      const [topicsResult, commentsResult, topicLikesResult, commentLikesResult] =
        await Promise.all([
          supabaseClient
            .from("community_topics")
            .select("id, author_id, author_name, title, body, tags, image_urls, created_at")
            .order("created_at", { ascending: false })
            .limit(100)
            .abortSignal(controller.signal),
          supabaseClient
            .from("community_comments")
            .select("id, topic_id, parent_id, author_id, author_name, body, created_at")
            .order("created_at", { ascending: true })
            .limit(500)
            .abortSignal(controller.signal),
          supabaseClient
            .from("community_topic_likes")
            .select("topic_id, user_id")
            .limit(2000)
            .abortSignal(controller.signal),
          supabaseClient
            .from("community_comment_likes")
            .select("comment_id, user_id")
            .limit(4000)
            .abortSignal(controller.signal),
        ]);
      const requestError =
        topicsResult.error ??
        commentsResult.error ??
        topicLikesResult.error ??
        commentLikesResult.error;
      if (requestError) {
        setError(copy.unavailable);
        return;
      }
      setTopics((topicsResult.data ?? []) as CommunityTopic[]);
      setComments((commentsResult.data ?? []) as CommunityComment[]);
      setTopicLikes((topicLikesResult.data ?? []) as TopicLike[]);
      setCommentLikes((commentLikesResult.data ?? []) as CommentLike[]);
    } catch {
      setError(copy.unavailable);
    } finally {
      window.clearTimeout(timeout);
      setLoading(false);
    }
  }, [copy.unavailable]);

  useEffect(() => {
    void loadCommunity();
  }, [loadCommunity]);

  useEffect(() => {
    if (!composerOpen && !selectedTopic) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [composerOpen, selectedTopic]);

  const filteredTopics = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase(locale);
    return topics.filter((topic) => {
      const matchesTag = !activeTag || topic.tags.includes(activeTag);
      const haystack = `${topic.title} ${topic.body} ${topic.tags.join(" ")}`
        .toLocaleLowerCase(locale);
      return matchesTag && (!normalized || haystack.includes(normalized));
    });
  }, [activeTag, locale, query, topics]);

  const visibleTopics = allTopicsView ? filteredTopics : filteredTopics.slice(0, 3);
  const selectedComments = selectedTopic
    ? comments.filter((comment) => comment.topic_id === selectedTopic.id)
    : [];

  const startTopic = () => {
    if (!account) {
      onRequireAccount();
      return;
    }
    setComposerOpen(true);
  };

  const addCustomTag = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter" && event.key !== ",") return;
    event.preventDefault();
    const value = customTag.trim().replace(/^#/u, "").slice(0, 24);
    if (value && !tags.includes(value) && tags.length < 5) setTags([...tags, value]);
    setCustomTag("");
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
        const path = `${account.id}/${crypto.randomUUID()}-${index}.${fileExtension(file)}`;
        const { error: uploadError } = await supabaseClient.storage
          .from("community-media")
          .upload(path, file, { cacheControl: "3600", upsert: false });
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
    setError(null);
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
      await loadCommunity();
    } catch (requestError) {
      await removeUploadedImages(uploadedPaths);
      setError(requestError instanceof Error ? requestError.message : copy.unavailable);
    } finally {
      setPublishing(false);
    }
  };

  const toggleTopicLike = async (topicId: string) => {
    if (!account || !supabaseClient) {
      onRequireAccount();
      return;
    }
    const liked = topicLikes.some(
      (like) => like.topic_id === topicId && like.user_id === account.id,
    );
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
      setError(requestError.message);
      return;
    }
    await loadCommunity();
  };

  const toggleCommentLike = async (commentId: string) => {
    if (!account || !supabaseClient) {
      onRequireAccount();
      return;
    }
    const liked = commentLikes.some(
      (like) => like.comment_id === commentId && like.user_id === account.id,
    );
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
      setError(requestError.message);
      return;
    }
    await loadCommunity();
  };

  const publishComment = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!account || !selectedTopic || !supabaseClient || !commentBody.trim()) return;
    const { error: requestError } = await supabaseClient.from("community_comments").insert({
      topic_id: selectedTopic.id,
      parent_id: replyTo?.id ?? null,
      author_id: account.id,
      author_name: account.displayName,
      body: commentBody.trim(),
    });
    if (requestError) {
      setError(requestError.message);
      return;
    }
    setCommentBody("");
    setReplyTo(null);
    await loadCommunity();
  };

  const topicLikeCount = (topicId: string) =>
    topicLikes.filter((like) => like.topic_id === topicId).length;
  const commentLikeCount = (commentId: string) =>
    commentLikes.filter((like) => like.comment_id === commentId).length;

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
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={copy.search}
            />
          </label>
          <button type="button" className="community-create-compact" onClick={startTopic}>
            <PenLine aria-hidden="true" />
            {copy.newTopic}
          </button>
        </header>

        <div className="community-tag-filter" aria-label={copy.tagsLabel}>
          {presets.map((tagName) => (
            <button
              key={tagName}
              type="button"
              className={activeTag === tagName ? "is-active" : ""}
              onClick={() => setActiveTag(activeTag === tagName ? null : tagName)}
            >
              #{tagName}
            </button>
          ))}
        </div>

        {visibleTopics.length === 0 ? (
          <div className={`community-starter${error ? " is-error" : ""}`}>
            <header>
              <h3>{copy.starterTitle}</h3>
              {error ? <p role="status">{error}</p> : null}
            </header>
            <ol>
              {copy.starterItems.map(([title, body], index) => (
                <li key={title}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <div><strong>{title}</strong><p>{body}</p></div>
                </li>
              ))}
            </ol>
          </div>
        ) : null}

        <div className="community-topic-grid">
          {visibleTopics.map((topic, index) => {
            const commentCount = comments.filter(
              (comment) => comment.topic_id === topic.id,
            ).length;
            const liked = Boolean(
              account &&
                topicLikes.some(
                  (like) => like.topic_id === topic.id && like.user_id === account.id,
                ),
            );
            return (
              <article key={topic.id}>
                <button
                  type="button"
                  className={`community-topic-cover is-tone-${(index % 4) + 1}`}
                  onClick={() => setSelectedTopic(topic)}
                  aria-label={`${copy.open}: ${topic.title}`}
                >
                  {topic.image_urls[0] ? (
                    <img src={topic.image_urls[0]} alt="" />
                  ) : (
                    <>
                      <Camera aria-hidden="true" />
                      <strong>{topic.title}</strong>
                    </>
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
                      onClick={() => void toggleTopicLike(topic.id)}
                    >
                      <Heart aria-hidden="true" />
                      {topicLikeCount(topic.id)}
                    </button>
                    <button type="button" onClick={() => setSelectedTopic(topic)}>
                      <MessageCircle aria-hidden="true" />
                      {commentCount}
                    </button>
                    <button type="button" onClick={() => setSelectedTopic(topic)}>
                      {copy.open}
                      <ArrowUpRight aria-hidden="true" />
                    </button>
                  </footer>
                </div>
              </article>
            );
          })}
        </div>

        {!loading && !error ? (
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
        <div className="community-modal-backdrop" role="presentation">
          <form
            className="community-composer"
            onSubmit={(event) => void publish(event)}
            aria-label={copy.newTopic}
          >
            <header>
              <div><PenLine aria-hidden="true" /><h2>{copy.newTopic}</h2></div>
              <button type="button" onClick={() => setComposerOpen(false)} aria-label={copy.close}>
                <X aria-hidden="true" />
              </button>
            </header>
            <label>
              <span>{copy.titleLabel}</span>
              <input
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
                <input
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
                <span>{copy.mediaHint}</span>
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp,image/gif"
                  multiple
                  onChange={(event) =>
                    setFiles(Array.from(event.target.files ?? []).slice(0, 4))
                  }
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
            {error ? <p className="community-form-error">{error}</p> : null}
            <footer>
              <button type="button" onClick={() => setComposerOpen(false)}>
                {copy.cancel}
              </button>
              <button
                type="submit"
                disabled={publishing || !title.trim() || !body.trim()}
              >
                <Send aria-hidden="true" />
                {publishing ? copy.publishing : copy.publish}
              </button>
            </footer>
          </form>
        </div>
      ) : null}

      {selectedTopic ? (
        <div className="community-modal-backdrop" role="presentation">
          <section
            className="community-topic-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="community-topic-title"
          >
            <button
              type="button"
              className="community-dialog-close"
              onClick={() => setSelectedTopic(null)}
              aria-label={copy.close}
            >
              <X aria-hidden="true" />
            </button>
            <div className="community-topic-dialog-visual">
              {selectedTopic.image_urls.length ? (
                selectedTopic.image_urls.map((url) => <img key={url} src={url} alt="" />)
              ) : (
                <div>
                  <MessageCircle aria-hidden="true" />
                  <strong>{selectedTopic.title}</strong>
                </div>
              )}
            </div>
            <div className="community-topic-dialog-content">
              <header>
                <div className="community-topic-author">
                  <span><UserRound aria-hidden="true" /></span>
                  <div>
                    <strong>{selectedTopic.author_name}</strong>
                    <time>{dateLabel(locale, selectedTopic.created_at)}</time>
                  </div>
                </div>
                <h2 id="community-topic-title">{selectedTopic.title}</h2>
                <p>{selectedTopic.body}</p>
                <div className="community-topic-tags">
                  {selectedTopic.tags.map((tagName) => (
                    <span key={tagName}>#{tagName}</span>
                  ))}
                </div>
                <button
                  type="button"
                  className={
                    account &&
                    topicLikes.some(
                      (like) =>
                        like.topic_id === selectedTopic.id &&
                        like.user_id === account.id,
                    )
                      ? "is-liked"
                      : ""
                  }
                  onClick={() => void toggleTopicLike(selectedTopic.id)}
                >
                  <Heart aria-hidden="true" />
                  {topicLikeCount(selectedTopic.id)} {copy.likes}
                </button>
              </header>
              <div className="community-comment-list">
                <h3>{copy.comments}</h3>
                {selectedComments.length === 0 ? (
                  <p className="community-no-comments">{copy.noComments}</p>
                ) : null}
                {selectedComments.map((comment) => {
                  const parent = comment.parent_id
                    ? selectedComments.find((candidate) => candidate.id === comment.parent_id)
                    : null;
                  const liked = Boolean(
                    account &&
                      commentLikes.some(
                        (like) =>
                          like.comment_id === comment.id &&
                          like.user_id === account.id,
                      ),
                  );
                  return (
                    <article key={comment.id} className={comment.parent_id ? "is-reply" : ""}>
                      <header>
                        <strong>{comment.author_name}</strong>
                        <time>{dateLabel(locale, comment.created_at)}</time>
                      </header>
                      {parent ? <small>@{parent.author_name}</small> : null}
                      <p>{comment.body}</p>
                      <footer>
                        <button
                          type="button"
                          className={liked ? "is-liked" : ""}
                          onClick={() => void toggleCommentLike(comment.id)}
                        >
                          <Heart aria-hidden="true" />{commentLikeCount(comment.id)}
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
                    required
                    maxLength={2000}
                    value={commentBody}
                    onChange={(event) => setCommentBody(event.target.value)}
                    placeholder={copy.commentPlaceholder}
                  />
                  <button type="submit" disabled={!commentBody.trim()}>
                    <Send aria-hidden="true" />{copy.sendComment}
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
