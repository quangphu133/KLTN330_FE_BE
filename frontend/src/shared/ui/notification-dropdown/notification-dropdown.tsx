// Ghi chú nhóm: Việt hóa hoặc tinh chỉnh hiển thị của thành phần giao diện dùng chung.
import { useCallback, useState } from 'react'
import { Dropdown } from '@/shared/ui/dropdown/dropdown'
import { DropdownItem } from '@/shared/ui/dropdown/dropdown-Item'
import { appRoutes } from '@/shared/constants/routes'
import {
  CallNotification,
  useGetNotificationsQuery,
  useMarkNotificationReadMutation,
} from '@/entities/notifications.api'
import { formatDates } from '@/shared/utils/date-utils'
import { useGetProfileQuery } from '@/entities/auth/auth.api'

type NotificationItemProps = {
  data: CallNotification
  onClose: () => void
  onRead: (id: number) => void
  destination?: string
}

const NotificationItem = ({ data, onClose, onRead, destination }: NotificationItemProps) => {
  const status = data.event_type === 'processing'
    ? 'Đang xử lý'
    : data.event_type === 'needs_confirmation'
      ? 'Cần xác nhận người nói'
      : data.event_type === 'insufficient_speakers'
        ? 'Thiếu dữ liệu người nói'
        : data.event_type === 'failed'
          ? 'Thất bại'
          : data.event_type === 'completed'
            ? 'Đã hoàn tất'
            : null

  return (
    <li>
      <DropdownItem
        tag={destination ? 'a' : 'button'}
        to={destination}
        onClick={() => onRead(data.id)}
        onItemClick={onClose}
        className="flex gap-3 rounded-lg border-b border-gray-100 p-3 px-4.5 py-3 hover:bg-gray-100 dark:border-gray-700 dark:hover:bg-gray-800"
      >
        <span className="block">
          <span className="mb-1.5 block text-theme-sm text-gray-500 dark:text-gray-400 space-x-1">
            <span className="font-medium text-gray-800 dark:text-white/90">
              {data.title || 'Thông báo mới'}
            </span>
          </span>
          <span className="mb-1 block text-theme-xs text-gray-600 dark:text-gray-300">
            {data.message}
          </span>

          {status && (
            <span className="mb-1 inline-block rounded-full bg-blue-50 px-2 py-0.5 text-theme-xs font-medium text-blue-700 dark:bg-blue-500/10 dark:text-blue-300">
              {status}
            </span>
          )}

          <span className="flex items-center gap-2 text-gray-500 text-theme-xs dark:text-gray-400">
            <span>{formatDates(data.created_at ? new Date(data.created_at) : null)}</span>
          </span>
        </span>
      </DropdownItem>
    </li>
  )
}

export const NotificationDropdown = () => {
  const [isOpen, setIsOpen] = useState(false)
  const {
    data: notifications = [],
    isError,
    isLoading,
  } = useGetNotificationsQuery(
    { offset: 0, limit: 50 },
    { pollingInterval: 10 * 1000, skipPollingIfUnfocused: true, refetchOnFocus: true }
  )
  const [markNotificationRead] = useMarkNotificationReadMutation()
  const { data: profile } = useGetProfileQuery()
  const visibleNotifications = profile?.role === 'admin'
    ? notifications
    : notifications.filter(notification =>
      !['needs_confirmation', 'insufficient_speakers', 'speaker_roles_pending'].includes(notification.event_type),
    )
  const notifying = visibleNotifications.some(notification => !notification.is_read)

  const handleRead = useCallback(
    (id: number) => {
      void markNotificationRead(id)
    },
    [markNotificationRead]
  )

  const toggleDropdown = useCallback(() => {
    setIsOpen(prev => !prev)
  }, [])

  const closeDropdown = useCallback(() => {
    setIsOpen(false)
  }, [])

  const handleClick = useCallback(() => {
    toggleDropdown()
  }, [toggleDropdown])

  return (
    <div className="relative">
      <button
        className="relative flex items-center cursor-pointer justify-center text-gray-500 transition-colors bg-white border border-gray-200 rounded-full dropdown-toggle hover:text-gray-700 h-11 w-11 hover:bg-gray-100 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-white"
        onClick={handleClick}
      >
        <span
          className={`absolute right-0 top-0.5 z-10 h-2 w-2 rounded-full bg-orange-400 ${
            !notifying ? 'hidden' : 'flex'
          }`}
        >
          <span className="absolute inline-flex w-full h-full bg-orange-400 rounded-full opacity-75 animate-ping"></span>
        </span>
        <svg
          className="fill-current"
          width="20"
          height="20"
          viewBox="0 0 20 20"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path
            fillRule="evenodd"
            clipRule="evenodd"
            d="M10.75 2.29248C10.75 1.87827 10.4143 1.54248 10 1.54248C9.58583 1.54248 9.25004 1.87827 9.25004 2.29248V2.83613C6.08266 3.20733 3.62504 5.9004 3.62504 9.16748V14.4591H3.33337C2.91916 14.4591 2.58337 14.7949 2.58337 15.2091C2.58337 15.6234 2.91916 15.9591 3.33337 15.9591H4.37504H15.625H16.6667C17.0809 15.9591 17.4167 15.6234 17.4167 15.2091C17.4167 14.7949 17.0809 14.4591 16.6667 14.4591H16.375V9.16748C16.375 5.9004 13.9174 3.20733 10.75 2.83613V2.29248ZM14.875 14.4591V9.16748C14.875 6.47509 12.6924 4.29248 10 4.29248C7.30765 4.29248 5.12504 6.47509 5.12504 9.16748V14.4591H14.875ZM8.00004 17.7085C8.00004 18.1228 8.33583 18.4585 8.75004 18.4585H11.25C11.6643 18.4585 12 18.1228 12 17.7085C12 17.2943 11.6643 16.9585 11.25 16.9585H8.75004C8.33583 16.9585 8.00004 17.2943 8.00004 17.7085Z"
            fill="currentColor"
          />
        </svg>
      </button>

      <Dropdown
        isOpen={isOpen}
        onClose={closeDropdown}
        className="absolute -right-[240px] mt-[17px] flex h-[480px] w-[350px] flex-col rounded-2xl border border-gray-200 bg-white p-3 shadow-theme-lg dark:border-gray-700 dark:bg-gray-900 sm:w-[361px] lg:right-0"
      >
        <div className="flex items-center justify-between pb-3 mb-3 border-b border-gray-100 dark:border-gray-700">
          <h5 className="text-lg font-semibold text-gray-800 dark:text-gray-100">Thông báo</h5>
          <button
            onClick={toggleDropdown}
            className="text-gray-500 transition dark:text-gray-400 hover:text-gray-700 dark:hover:text-white"
          >
            <svg
              className="fill-current"
              width="24"
              height="24"
              viewBox="0 0 24 24"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M6.21967 7.28131C5.92678 6.98841 5.92678 6.51354 6.21967 6.22065C6.51256 5.92775 6.98744 5.92775 7.28033 6.22065L11.999 10.9393L16.7176 6.22078C17.0105 5.92789 17.4854 5.92788 17.7782 6.22078C18.0711 6.51367 18.0711 6.98855 17.7782 7.28144L13.0597 12L17.7782 16.7186C18.0711 17.0115 18.0711 17.4863 17.7782 17.7792C17.4854 18.0721 17.0105 18.0721 16.7176 17.7792L11.999 13.0607L7.28033 17.7794C6.98744 18.0722 6.51256 18.0722 6.21967 17.7794C5.92678 17.4865 5.92678 17.0116 6.21967 16.7187L10.9384 12L6.21967 7.28131Z"
                fill="currentColor"
              />
            </svg>
          </button>
        </div>
        <div className="flex justify-between items-center px-1 mb-2 text-theme-sm">
          <span className="text-gray-500 dark:text-gray-300">
            {visibleNotifications.length} thông báo
          </span>
        </div>
        <ul className="flex flex-col h-auto overflow-y-auto custom-scrollbar">
          {isError && (
            <li className="py-3 text-center text-sm text-red-600 dark:text-red-300">
              Không thể tải thông báo. Dữ liệu cũ (nếu có) vẫn được giữ lại.
            </li>
          )}
          {visibleNotifications.length > 0 ? (
            visibleNotifications.map(notification => (
              <NotificationItem
                key={notification.id}
                data={notification}
                onClose={closeDropdown}
                onRead={handleRead}
                destination={
                  notification.job_status === 'completed' && notification.call_record_id !== null
                    ? appRoutes.private.call(String(notification.call_record_id))
                    : undefined
                }
              />
            ))
          ) : isLoading ? (
            <li className="py-8 text-center text-gray-500 dark:text-gray-300">
              Đang tải thông báo...
            </li>
          ) : isError ? null : (
            <li className="py-8 text-center text-gray-500 dark:text-gray-300">
              Không có thông báo mới
            </li>
          )}
        </ul>
      </Dropdown>
    </div>
  )
}
