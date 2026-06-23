export interface FileUploadProps {
  accept?: string
  multiple?: boolean
  maxSize?: number
  maxFiles?: number
  disabled?: boolean
  loading?: boolean
  onUpload?: (files: File[]) => void | Promise<void>
  onChange?: (files: File[]) => void
  onError?: (error: string) => void
  placeholder?: string
  description?: string
  showPreview?: boolean
  dragAndDrop?: boolean
}

export interface FileUploadState {
  files: File[]
  isDragging: boolean
  isUploading: boolean
  error: string | null
}
