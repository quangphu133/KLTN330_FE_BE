'use client'

import React from 'react'
import type {
  KeywordRegion,
  SpeakerRoleMapping,
} from '@/entities/mediafile/api/mediafile.types'

interface ChecklistProps {
  complianceScore: number | null | undefined
  findings: KeywordRegion[] | null | undefined
  roleMapping: SpeakerRoleMapping | null | undefined
  isLoading: boolean
  isError: boolean
}

const formatTimestamp = (seconds: number) => {
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = Math.floor(seconds % 60)
  return `${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`
}

export const Checklist: React.FC<ChecklistProps> = ({
  complianceScore,
  findings,
  roleMapping,
  isLoading,
  isError,
}) => {
  if (isLoading) {
    return <p className="rounded-lg border border-gray-200 p-4 text-sm text-gray-600 dark:border-gray-700 dark:text-gray-300">Đang tải kết quả kiểm tra...</p>
  }

  if (isError) {
    return <p role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200">Không thể tải kết quả kiểm tra cho cuộc gọi này.</p>
  }

  if (complianceScore == null) {
    const message = roleMapping?.status === 'pending'
      ? 'Đang chờ quản trị viên xác nhận vai trò người nói. Cuộc gọi chưa được chấm điểm.'
      : 'Chưa có kết quả chấm điểm được lưu cho cuộc gọi này.'

    return (
      <section className="space-y-3 rounded-xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-900/60 dark:bg-amber-950/30">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Kết quả kiểm tra tự động</h2>
        <p className="text-sm text-amber-800 dark:text-amber-200">{message}</p>
      </section>
    )
  }

  const savedFindings = findings ?? []

  return (
    <section className="space-y-4 text-gray-700 dark:text-gray-300">
      <div className="rounded-xl border border-gray-200 p-4 dark:border-gray-700">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Kết quả kiểm tra tự động</h2>
        <div className="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <p className="text-2xl font-semibold text-green-700 dark:text-green-300">
            {complianceScore} <span className="text-base font-normal">/ 100</span>
          </p>
          <p className="text-sm">{savedFindings.length} vi phạm được lưu trong kết quả đánh giá</p>
        </div>
      </div>

      {savedFindings.length === 0 ? (
        <p className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm dark:border-gray-700 dark:bg-gray-900">
          Không có vi phạm được ghi nhận trong kết quả đã lưu.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-700">
          <table className="min-w-[680px] w-full border-collapse text-left text-sm">
            <thead className="bg-gray-50 text-gray-700 dark:bg-gray-900 dark:text-gray-200">
              <tr>
                <th scope="col" className="px-4 py-3 font-semibold">Tiêu chí vi phạm</th>
                <th scope="col" className="px-4 py-3 font-semibold">Bằng chứng đã lưu</th>
                <th scope="col" className="px-4 py-3 font-semibold">Mốc tham khảo</th>
                <th scope="col" className="px-4 py-3 text-right font-semibold">Điểm trừ</th>
              </tr>
            </thead>
            <tbody>
              {savedFindings.map((finding, index) => (
                <tr key={`${finding.categoryName ?? finding.displayName ?? 'finding'}-${index}`} className="border-t border-gray-200 dark:border-gray-700">
                  <th scope="row" className="px-4 py-3 align-top font-medium text-gray-900 dark:text-gray-100">
                    {finding.displayName || 'Vi phạm đã lưu'}
                    {finding.phrase && <span className="mt-1 block font-normal text-gray-600 dark:text-gray-400">Từ khóa: {finding.phrase}</span>}
                  </th>
                  <td className="max-w-xl whitespace-pre-wrap px-4 py-3 align-top">{finding.snippet || 'Không có bằng chứng văn bản được lưu.'}</td>
                  <td className="whitespace-nowrap px-4 py-3 align-top">
                    {finding.hasTimestamp && Number.isFinite(finding.startTime) && finding.startTime >= 0
                      ? formatTimestamp(finding.startTime)
                      : 'Không lưu thời điểm'}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right align-top text-red-700 dark:text-red-300">
                    {finding.deduction == null ? 'Chưa lưu số điểm trừ' : `−${finding.deduction} điểm`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
