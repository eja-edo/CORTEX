export type RecordingType = 'audio' | 'video'

export type Recording = {
    id: string
    type: RecordingType
    name: string
    blob: Blob
    url: string
    duration: number
    createdAt: Date
    uploadState: 'idle' | 'uploading' | 'uploaded' | 'failed'
    uploadProgress: number
    uploadSessionId?: string
    uploadedObjectKey?: string
    uploadedAssetId?: string
    uploadError?: string
}

export type AuthRequest = <T>(path: string, init?: RequestInit) => Promise<T>
