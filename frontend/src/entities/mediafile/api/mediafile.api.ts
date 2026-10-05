import { commonApi } from '@/entities/common/base-query';
import {
  CreateMediaFileRequest,
  AsrJob,
  MediaFile,
  MediaFileRequest,
  MediaFileResponse,
  MediaFileResultRequest,
  MediaFileResultResponse,
} from '@/entities/mediafile/api/mediafile.types';

export const MediaFileApi = commonApi.injectEndpoints({
  endpoints: (builder) => ({
    createMediaFile: builder.mutation<AsrJob, CreateMediaFileRequest>({
      query: ({ file, queryParams }) => {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('createDate', queryParams.createDate);
        formData.append('clientNumber', queryParams.clientNumber);
        if (queryParams.telesaleId !== undefined) {
          formData.append('telesale_id', String(queryParams.telesaleId));
        }
        if (queryParams.projectId !== undefined) {
          formData.append('projectId', String(queryParams.projectId));
        }

        return {
          url: 'api/transcribe/upload',
          method: 'POST',
          body: formData,
        };
      },
      invalidatesTags: ['MEDIAFILE', 'NOTIFICATIONS'],
    }),

    getMediaFilesQuery: builder.query<MediaFileResponse, MediaFileRequest>({
      query: (params) => {
        return {
          url: 'api/mediafile/',
          method: 'GET',
          params,
        };
      },

      providesTags: ['MEDIAFILE'],
    }),
    getMediaFileById: builder.query<MediaFile, { id: number }>({
      providesTags: ['MEDIAFILE'],
      query: (args) => {
        const { id, ...params } = args;
        return {
          method: 'GET',
          url: `api/mediafile/${id}`,
          params: params,
        };
      },
    }),
    getMediaFileStream: builder.query<void, { id: number }>({
      providesTags: ['MEDIAFILE'],
      query: (args) => {
        const { id, ...params } = args;
        return {
          method: 'GET',
          url: `api/mediafile/${id}/stream`,
          params: params,
        };
      },
    }),
    getMediaFileResult: builder.query<
      MediaFileResultResponse,
      MediaFileResultRequest
    >({
      providesTags: ['MEDIAFILE'],
      query: (args) => {
        const { id, ...params } = args;
        return {
          method: 'GET',
          url: `api/mediafile/${id}/result`,
          params: params,
        };
      },
    }),
    confirmSpeakerRoles: builder.mutation<
      MediaFileResultResponse,
      { id: number; agentSpeakerId: string }
    >({
      query: ({ id, agentSpeakerId }) => ({
        url: `api/mediafile/${id}/speaker-roles`,
        method: 'PUT',
        body: { agentSpeakerId },
      }),
      invalidatesTags: ['MEDIAFILE', 'ANALYTICS_DASHBOARD', 'NOTIFICATIONS'],
    }),
    confirmWordRoles: builder.mutation<
      MediaFileResultResponse,
      {
        id: number;
        assignments: { startWordId: number; endWordId: number; role: 'agent' | 'customer' }[];
      }
    >({
      query: ({ id, assignments }) => ({
        url: `api/mediafile/${id}/word-roles`,
        method: 'PUT',
        body: {
          assignments: assignments.map(({ startWordId, endWordId, role }) => ({
            startWordId,
            endWordId,
            role,
          })),
        },
      }),
      invalidatesTags: ['MEDIAFILE', 'ANALYTICS_DASHBOARD', 'NOTIFICATIONS'],
    }),
    deleteCallRecord: builder.mutation<
      { status: string; message: string },
      { id: number; reason: string }
    >({
      query: ({ id, reason }) => ({
        url: `api/calls/${id}`,
        method: 'DELETE',
        body: { reason },
      }),
      invalidatesTags: ['MEDIAFILE'],
    }),
    getDownloadFileExcel: builder.query<string, void>({
      query: () => ({
        url: 'api/mediafile/export/excel',
        method: 'GET',
        responseHandler: async (response: Response) => {
          if (response.ok) {
            return response.blob();
          }

          const text = await response.text();
          try {
            return JSON.parse(text);
          } catch {
            return {
              message: text || `Không thể tải file Excel (${response.status})`,
              status: response.status,
            };
          }
        },
      }),
      transformResponse: (blob: Blob) => {
        return URL.createObjectURL(blob);
      },
    }),
  }),
});

export const {
  useCreateMediaFileMutation,
  useGetMediaFilesQueryQuery,
  useGetMediaFileByIdQuery,
  useLazyGetDownloadFileExcelQuery,
  useGetMediaFileResultQuery,
  useConfirmSpeakerRolesMutation,
  useConfirmWordRolesMutation,
  useDeleteCallRecordMutation,
} = MediaFileApi;
