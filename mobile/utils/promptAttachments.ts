export interface PromptAttachment {
  id: string;
  uri: string;
  name: string;
  type: 'image' | 'video' | 'document' | 'audio';
}

export const getPromptAttachments = (
  queuedAttachments: readonly PromptAttachment[] | undefined,
  composerAttachments: readonly PromptAttachment[],
): PromptAttachment[] => [...(queuedAttachments ?? composerAttachments)];
