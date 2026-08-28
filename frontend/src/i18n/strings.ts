export interface TemplateVar {
  label: string
  value: string
}

export const strings = {
  // ── Auth ──
  auth: {
    brand: {
      logo: 'C',
      name: 'Cortex',
      tagline: 'Trình lập kế hoác học thuật cá nhân của bạn',
      copyright: '© 2024 Cortex Academic. All rights reserved.',
    },
    card: {
      title: 'Chào mừng đến với Cortex',
      subtitle: 'Trình lập kế hoạch học thuật cá nhân của bạn',
    },
    tabs: {
      login: 'Đăng nhập',
      register: 'Tạo tài khoản',
    },
    login: {
      emailLabel: 'Email',
      emailPlaceholder: 'you@university.edu',
      passwordLabel: 'Mật khẩu',
      passwordPlaceholder: '••••••••',
      submit: 'Tiếp tục',
      submitting: 'Đang đăng nhập…',
    },
    register: {
      nameLabel: 'Họ và tên',
      namePlaceholder: 'Alice Smith',
      emailLabel: 'Email',
      emailPlaceholder: 'you@university.edu',
      passwordLabel: 'Mật khẩu',
      passwordPlaceholder: 'Ít nhất 8 ký tự',
      submit: 'Tạo tài khoản',
      submitting: 'Đang tạo tài khoản…',
    },
    divider: {
      or: 'Hoặc',
      continueWith: 'Tiếp tục với',
    },
    social: {
      google: 'Google',
      apple: 'Apple',
      microsoft: 'Microsoft',
    },
    footer: {
      forgotPassword: 'Quên mật khẩu?',
      help: 'Trợ giúp',
      privacy: 'Chính sách bảo mật',
      terms: 'Điều khoản dịch vụ',
    },
  },

  // ── Global Home ──
  home: {
    greeting: {
      morning: 'Chào buổi sáng',
      afternoon: 'Chào buổi chiều',
      evening: 'Chào buổi tối',
    },
    upcoming: {
      title: 'Sắp tới',
    },
    today: 'Hôm nay',
    tomorrow: 'Ngày mai',
    noUpcomingEvents: {
      title: 'Không có sự kiện sắp tới',
      desc: 'Sự kiện từ lịch của bạn sẽ xuất hiện ở đây.',
    },
    projects: {
      title: 'Dự án',
      createBtn: 'Tạo dự án',
      empty: {
        title: 'Chưa có dự án nào',
        // Nói ra *cửa chính*, không chỉ cửa phụ: phần lớn dự án sinh ra từ
        // một channel có việc (DESIGN 4.1), không do ai bấm nút tạo.
        desc: 'Dự án xuất hiện khi có việc từ một channel. Bạn cũng có thể tạo tay.',
      },
    },
    recentActivity: {
      title: 'Hoạt động gần đây',
      noRecentNotes: {
        title: 'Không có ghi chú gần đây',
        desc: 'Hoạt động từ các luồng của bạn sẽ xuất hiện ở đây.',
      },
    },
    timeAgo: {
      justNow: 'Vừa mới',
      hours: (n: number) => `${n}h trước`,
      days: (n: number) => `${n} ngày trước`,
    },
  },

  // ── Settings ──
  settings: {
    title: 'Cài đặt',
    appearance: {
      title: 'Giao diện',
      desc: 'Chọn chủ đề bạn thích cho giao diện.',
    },
    notes: {
      title: 'Ghi chú',
      desc: 'Cấu hình cách ghi chú được hiển thị và chỉnh sửa.',
      editBlocks: {
        label: 'Chỉnh sửa khối',
        desc: 'Cho phép chỉnh sửa nội dung ghi chú trực tiếp từ trình soạn thảo khối (Chia tách / Khối). Khi tắt, chỉnh sửa chỉ khả dụng ở chế độ Markdown thô.',
      },
    },
    notifications: {
      title: 'Thông báo',
      desc: 'Giờ âm thầm tạm dừng các nhắc nhở không khẩn cấp; danh sách bên dưới cho phép tắt hoàn toàn từng loại.',
      quietHoursStart: 'Giờ âm thầm bắt đầu (UTC)',
      quietHoursEnd: 'Giờ âm thầm kết thúc (UTC)',
      save: 'Lưu',
      clear: 'Xóa',
      autoDowngraded: (level: string, count: number) =>
        `Tự hạ xuống "${level}" sau ${count} lần bị bỏ qua`,
    },
    googleCalendar: {
      title: 'Google Calendar',
      desc: 'Quản lý kết nối và đồng bộ thủ công cho tích hợp lịch của bạn.',
      connectBtn: 'Kết nối Google',
      reconnectBtn: 'Kết nối lại Google',
      disconnectBtn: 'Ngắt kết nối Google',
      syncBtn: 'Đồng bộ Google',
      startWatchBtn: 'Bắt đầu theo dõi',
      renewWatchBtn: 'Gia hạn theo dõi',
      status: {
        notConnected: 'Chưa kết nối',
        needsReconnect: 'Cần kết nối lại',
        connected: 'Đã kết nối',
      },
      lastSync: 'Lần đồng bộ cuối',
      channelExpires: 'Kênh hết hạn',
      lastError: 'Lỗi cuối cùng',
    },
  },

  // ── App navigation ──
   nav: {
    // "Hôm nay", không phải "Trang chủ": màn này trả lời *giờ tôi nên làm
    // gì*, và tên của nó là một phần của câu trả lời đó (DESIGN 10.2).
    home: 'Hôm nay',
    notifications: 'Thông báo',
    schedule: 'Lịch',
    // "Việc" — bề mặt tra cứu và sửa, phạm vi là dự án đang mở (DESIGN 10.2).
    tasks: 'Việc',
    records: 'Bản ghi',
    workflows: 'Workflow',
    settings: 'Cài đặt',
    notes: 'Ghi chú',
    newNote: 'Ghi chú mới',
    addSubNote: 'Thêm ghi chú con',
    newWorkflow: 'Workflow mới',
    loading: 'Đang tải…',
    noRecordings: 'Chưa có bản ghi nào',
    noWorkflows: 'Chưa có workflow nào',
    noNotesYet: 'Chưa có ghi chú nào',
    deleteTitle: 'Xoá',
  },

  // ── Dự án (DESIGN 10.1 / 10.2) ──
  projects: {
    switcherLabel: 'Dự án',
    none: 'Chưa có dự án',
    yourProjects: 'Dự án của bạn',
    // Nguồn gốc, hiển thị cho người dùng. "Từ channel" trả lời câu họ hay
    // hỏi nhất về một dự án họ không nhớ đã tạo — vì họ chưa từng tạo nó.
    originDerived: 'Từ channel',
    originManual: 'Tạo tay',
    originPersonal: 'Cá nhân',
    rename: 'Đổi tên',
    renameFailed: 'Không đổi được tên dự án.',
    createFailed: 'Không tạo được dự án.',
    // Nhãn của dự án cá nhân trong dropdown. Nó là *giá trị mặc định khi
    // người dùng không nói gì khác*, không phải nơi chứa đồ thất lạc — nên
    // nó mang tên thật của người dùng, không phải "Khác" hay "Chưa phân loại".
    personalFallback: 'Cá nhân',
    newProject: 'Dự án mới…',
    newProjectPrompt: 'Tên dự án',
    moveLabel: 'Thuộc dự án',
    moving: 'Đang chuyển…',
    moveFailed: 'Không chuyển được dự án. Thử lại nhé.',
    moved: (name: string) => `Đã chuyển sang ${name}`,
    empty: 'Chưa có dự án nào',
    // Màn Việc trống. Nói ra *vì sao* nó trống: dự án sinh ra từ channel
    // có việc (4.1), không phải từ một nút "Tạo dự án".
    emptyHint: 'Dự án xuất hiện khi có việc từ một channel. Bạn cũng có thể tạo tay.',
    noOpenTasks: 'Không còn việc nào đang mở trong dự án này',
    openCount: (n: number) => `${n} việc đang mở`,
    deadlineNone: 'Không hạn',
    deadlineIn: (days: number) => (days < 0 ? `Quá hạn ${-days} ngày` : days === 0 ? 'Hạn hôm nay' : `Còn ${days} ngày`),
    loadFailed: 'Không tải được danh sách dự án',
  },

  // ── Records / Assets ──
   records: {
    title: 'Bản ghi',
    loading: 'Đang tải…',
    noRecordings: 'Chưa có bản ghi nào',
    noRecordingsDesc: 'Bắt đầu quay màn hình hoặc thu âm ở trên',
    cloudStorage: 'Lưu trữ đám mây',
    refreshTitle: 'Làm mới',
    headerTitle: 'Bản ghi',
    justNow: 'Vừa xong',
    minAgo: ' phút trước',
    hourAgo: ' giờ trước',
    dayAgo: ' ngày trước',
    status: {
      ready: 'Sẵn sàng',
      processing: 'Đang xử lý',
      pending: 'Đang chờ',
      error: 'Lỗi',
      completed: 'Hoàn thành',
    },
    menu: {
      rename: 'Đổi tên',
      download: 'Tải xuống',
      process: 'Xử lý với AI',
      processAI: 'Xử lý bằng AI',
      viewKnowledge: 'Xem tri thức',
      delete: 'Xoá',
    },
    processDialog: {
      title: 'Xử lý bản ghi?',
      desc: 'Trích xuất bản ghi, văn bản và hiểu biết bằng phân tích AI',
      skip: 'Bỏ qua',
      processNow: 'Xử lý ngay',
      processing: 'Đang xử lý…',
    },
    error: {
      cannotLoad: 'Không thể tải bản ghi từ máy chủ',
      cannotPlay: 'Không thể phát media',
      cannotDownload: 'Không thể tải xuống media',
      cannotDelete: 'Không xóa được bản ghi',
      cannotRename: 'Không đổi tên được bản ghi',
      cannotProcess: 'Không thể bắt đầu xử lý',
      noUploadId: 'No upload ID on asset',
    },
    live: {
      label: 'LIVE',
      screenCapture: 'Screen capture',
      audioCapture: 'Audio capture',
      listening: 'Listening…',
      rec: 'REC',
    },
  },

  // ── Search ──
  search: {
    placeholder: 'Tìm kiếm ghi chú…',
    noResults: (query: string) => `Không tìm thấy kết quả cho "${query}"`,
    recentNotes: 'Ghi chú gần đây',
    resultsCount: (n: number) => `${n} kết quả`,
    navigate: '↑↓ di chuyển',
    open: '↵ mở',
    close: 'Esc đóng',
  },

  // ── App topbar ──
  topbar: {
    searchPlaceholder: 'Tìm kiếm workflows, nodes, lịch sử...',
    askAI: 'Hỏi AI',
    help: 'Trợ giúp',
  },

  // ── Sync summary (SSE) ──
  sync: {
    summary: (source: string, created: number, updated: number, deleted: number, skipped: number) =>
      `${source} đồng bộ: +${created} / ~${updated} / -${deleted} (bỏ qua ${skipped})`,
    googleCalendarConnected: 'Google Calendar kết nối thành công.',
    googleConnectionFailed: (reason?: string) =>
      reason ? `Kết nối Google thất bại: ${reason}` : 'Kết nối Google thất bại',
  },

  // ── Status messages ──
  status: {
    noteCreated: 'Ghi chú đã được tạo.',
    noteDeleted: 'Đã xóa ghi chú.',
    cannotCreateNote: 'Không thể tạo ghi chú',
    cannotDeleteNote: 'Không thể xóa ghi chú',
    recordDeleted: 'Đã xoá bản ghi.',
    cannotDeleteRecord: 'Không xoá được bản ghi. Thử lại sau.',
    workflowDeleted: 'Đã xoá workflow.',
    cannotDeleteWorkspace: 'Không xoá được workspace. Thử lại sau.',
    workspaceDeleted: (name: string) => `Đã xoá workspace "${name}".`,
    cannotDeletePersonalWorkspace: 'Không thể xoá workspace cá nhân.',
  },

  // ── Confirm dialogs ──
  confirm: {
    deleteNote: {
      title: 'Xoá note',
      message: (title: string) => `Xoá "${title || 'Untitled'}"? Các note con cũng sẽ bị xoá.`,
    },
    deleteRecord: {
      title: 'Xoá bản ghi',
      message: (title: string) => `Xoá "${title || 'bản ghi này'}"? Không thể hoàn tác.`,
    },
    deleteWorkflow: {
      title: 'Xoá workflow',
      message: (name: string) => `Xoá "${name || 'workflow này'}"? Không thể hoàn tác.`,
    },
    deleteWorkspace: {
      title: 'Xoá workspace',
      message: (name: string) => `Xoá "${name}"? Toàn bộ nội dung bên trong sẽ mất và không thể hoàn tác.`,
    },
    delete: 'Xoá',
    cancel: 'Huỷ',
  },

  // ── Workflow Builder ──
  workflow: {
    toolbar: {
      backTitle: 'Quay lại',
      namePlaceholder: 'Tên workflow...',
      save: 'Lưu',
      saving: 'Đang lưu…',
      activate: 'Kích hoạt',
      pause: 'Tạm dừng',
      run: 'Chạy',
      resume: 'Tiếp tục',
      reactivate: 'Kích hoạt lại',
      delete: 'Xóa',
    },
    list: {
      title: 'Workflow',
      subtitle: 'Tự động hoá quy trình của bạn với workflow trực quan',
      createBtn: 'Tạo workflow mới',
      searchPlaceholder: 'Tìm kiếm workflows...',
      filters: {
        all: 'Tất cả',
        active: 'Hoạt động',
        draft: 'Bản nháp',
      },
      sort: {
        updated: 'Cập nhật gần đây',
        name: 'Tên',
      },
      empty: {
        noMatch: 'Không có workflow nào khớp với bộ lọc.',
        clearFilters: 'Xóa bộ lọc',
        noWorkflows: 'Chưa có workflow nào. Tạo workflow tự động đầu tiên.',
        createBtn: 'Tạo workflow',
        loading: 'Đang tải workflows...',
      },
      status: {
        draft: 'Bản nháp',
        active: 'Hoạt động',
        paused: 'Tạm dừng',
        archived: 'Lưu trữ',
      },
      actions: {
        edit: 'Sửa',
        open: 'Mở',
        more: 'Thêm',
        delete: 'Xóa',
      },
      timeAgo: {
        justNow: 'Vừa mới',
        minutes: (n: number) => `${n} phút trước`,
        hours: (n: number) => `${n} giờ trước`,
        days: (n: number) => `${n} ngày trước`,
      },
    },
    palette: {
      nodeLibrary: 'Thư viện node',
      searchPlaceholder: 'Tìm kiếm nodes...',
      addStickyNote: 'Thêm ghi chú dán',
      categories: {
        trigger: 'Triggers',
        webhook: 'Webhooks',
        action: 'Actions',
        ai: 'AI',
        condition: 'Conditions',
        wait: 'Wait',
      },
    },
    canvas: {
      // Technical labels stay in English
    },
    builder: {
      nodeConfig: {
        title: 'Cấu hình node',
        params: 'THAM SỐ',
        typeLabel: 'TYPE',
        labelLabel: 'LABEL',
        configJson: 'CONFIG (JSON)',
        triggerType: 'TRIGGER TYPE',
        primaryTrigger: "Primary trigger — determines the workflow's main trigger_type",
        supplementaryTrigger: 'Additional trigger — runs alongside the primary trigger',
        output: 'OUTPUT',
        success: 'Thành công',
        failed: 'Thất bại',
        runNode: 'Chạy node',
        running: 'Đang chạy...',
        removeNode: 'Xóa node',
        untitled: 'Untitled Workflow',
        saveError: (msg: string) => `Không thể kích hoạt workflow: ${msg}`,
        activateError: (msg: string) => `Không thể kích hoạt workflow: ${msg}`,
        activateErrorNoService: 'Không thể kích hoạt workflow. Dịch vụ workflow có đang chạy?',
        nodeError: 'Không thể thực thi node. Dịch vụ workflow có đang chạy?',
        saveFirst: 'Vui lòng lưu workflow trước khi chạy một node.',
        triggered: (id: string) => `Workflow triggered (ID: ${id}…)`,
        triggerError: (msg: string) => `Không thể kích hoạt workflow: ${msg}`,
        conflictWarning: 'Có thể bắn thông báo trùng',
        stickyNoteLabel: 'Sticky Note',
      },
    },
    config: {
      scheduleTrigger: {
        title: 'Edit Schedule Time',
        subtitle: 'Set when this workflow should run',
        timeLabel: 'Time',
        repeatLabel: 'Repeat',
        endDateLabel: 'End Date (optional)',
        previewLabel: 'Preview',
        nextRunsLabel: 'Next Runs',
        cancel: 'Cancel',
        addTime: 'Add Time',
        save: 'Save',
        scheduleLabel: 'Schedule',
        noScheduleConfigured: 'No schedule times configured. Add one or more times for this workflow to run automatically.',
        addTimeBtn: 'Add time',
        errorRequired: 'Time is required',
        errorInvalid: 'Invalid time',
        freq: {
          daily: 'Daily',
          weekly: 'Weekly (same weekday)',
          monthly: 'Monthly (same date)',
        },
      },
    },
  },

  // ── Config panels ──
  config: {
    createNote: {
      titleLabel: 'Title',
      titlePlaceholder: 'Note title',
      contentLabel: 'Content',
      contentPlaceholder: 'Note content with {{trigger.title}}',
      hint: 'Supports template variables',
      markdownHint: 'Markdown supported, supports template variables',
    },
    updateNote: {
      noteIdLabel: 'Note ID',
      noteIdPlaceholder: 'e.g. {{trigger.note_id}}',
      hint: 'Supports template variables',
      contentLabel: 'Content',
      contentPlaceholder: 'Updated content with {{trigger.title}}',
      markdownHint: 'Markdown supported, supports template variables',
      appendLabel: 'Append to existing content',
    },
    createTask: {
      titleLabel: 'Title',
      titlePlaceholder: 'Task title',
      hint: 'Supports template variables',
      descriptionLabel: 'Description',
      descriptionPlaceholder: 'Optional description',
      dueDateLabel: 'Due Date',
      dueDatePlaceholder: '2025-01-15T09:00:00 or {{trigger.due_date}}',
      dueDateHint: 'ISO 8601 or template variable. Optional',
      priorityLabel: 'Priority',
      priorityNone: 'None',
      priorityLow: 'Low',
      priorityMedium: 'Medium',
      priorityHigh: 'High',
      priorityUrgent: 'Urgent',
    },
    updateTask: {
      taskIdLabel: 'Task ID',
      taskIdPlaceholder: '{{trigger.task_id}}',
      hint: 'Supports template variables',
      titleLabel: 'Title',
      titlePlaceholder: 'Leave empty to keep unchanged',
      statusLabel: 'Status',
      statusUnchanged: 'Unchanged',
      statusTodo: 'Todo',
      statusInProgress: 'In Progress',
      statusDone: 'Done',
      statusCancelled: 'Cancelled',
      dueDateLabel: 'Due Date',
      dueDatePlaceholder: 'Leave empty to keep unchanged',
      priorityLabel: 'Priority',
      priorityNone: 'Unchanged',
      priorityLow: 'Low',
      priorityMedium: 'Medium',
      priorityHigh: 'High',
      priorityUrgent: 'Urgent',
    },
    sendNotification: {
      titleLabel: 'Tiêu đề',
      titlePlaceholder: 'VD: Đã tạo ghi chú mới',
      typeLabel: 'Loại',
      bodyLabel: 'Nội dung',
      bodyPlaceholder: 'VD: Ghi chú đã được tạo thành công',
      typeInfo: 'Info',
      typeSuccess: 'Success',
      typeWarning: 'Warning',
      typeError: 'Error',
    },
    schedule: {
      titleLabel: 'Title',
      titlePlaceholder: 'Event title',
      hint: 'Supports template variables',
      startTimeLabel: 'Start Time',
      startTimePlaceholder: '2025-01-15T09:00:00Z or {{trigger.time}}',
      startTimeHint: 'ISO 8601 or template variable',
      endTimeLabel: 'End Time',
      endTimePlaceholder: '2025-01-15T10:00:00Z or {{trigger.time}}',
      endTimeHint: 'ISO 8601 or template variable',
      descriptionLabel: 'Description',
      descriptionPlaceholder: 'Optional description',
    },
    callAI: {
      promptLabel: 'Prompt',
      promptPlaceholder: 'What do you want the AI to do? e.g. Summarize: {{trigger.title}}',
      hint: 'Supports template variables',
      systemInstructionLabel: 'System Instruction',
      systemInstructionPlaceholder: 'Optional system instruction',
      maxTokensLabel: 'Max Tokens',
      maxTokensPlaceholder: '1024',
      temperatureLabel: 'Temperature',
      temperaturePlaceholder: '0.7',
    },
    callApi: {
      methodLabel: 'Method',
      urlLabel: 'URL',
      urlPlaceholder: 'https://api.example.com/resource',
      paramsLabel: 'Params',
      keyPlaceholder: 'Key',
      valuePlaceholder: 'Value',
      addParam: 'Add param',
      paramsHint: 'Được nối vào URL dưới dạng query string. Hỗ trợ template variables.',
      authLabel: 'Authorization',
      authNone: 'None',
      authBearer: 'Bearer Token',
      authBasic: 'Basic Auth',
      authApiKey: 'API Key',
      bearerPlaceholder: '{{trigger.token}}',
      basicUsernamePlaceholder: 'Username',
      basicPasswordPlaceholder: 'Password',
      apiKeyPlaceholder: 'Key (e.g. X-API-Key)',
      apiValuePlaceholder: 'Value',
      addToHeader: 'Add to Header',
      addToQuery: 'Add to Query Params',
      headersLabel: 'Headers',
      addHeader: 'Add header',
      bodyLabel: 'Body',
      bodyPlaceholder: '{"message": "{{trigger.body}}"} — bỏ trống nếu method là GET',
      bodyHint: 'Chuỗi thô (không parse JSON ở đây) — khớp đúng kiểu string mà action.call_api nhận. Hỗ trợ template variables.',
      responseHint: "Response sẽ tự parse theo Content-Type: JSON → object, XML → dict lồng nhau, HTML/text → giữ nguyên chuỗi. Xem ở '{{steps.<label>.body}}'.",
    },
    extractHtml: {
      htmlLabel: 'HTML',
      htmlPlaceholder: '{{steps.callApi.body}}',
      htmlHint: 'Chuỗi HTML nguồn, hỗ trợ template variables — thường lấy từ output của action.call_api.',
      cssSelectorLabel: 'CSS Selector',
      cssSelectorPlaceholder: '.class-name, #id, table tr td',
      extractLabel: 'Extract',
      attributeLabel: 'Attribute',
      attributePlaceholder: 'href, src...',
      extractText: 'text',
      extractHtml: 'html',
      extractAttribute: 'attribute',
      extractDom: 'dom',
      multipleCheckbox: 'Lấy tất cả phần tử khớp (mảng) thay vì chỉ phần tử đầu tiên',
      domHint: "Trả về cây JSON đệ quy {'{tag, attributes, text|children}'} của toàn bộ phần tử khớp — không cần biết trước cấu trúc tag bên trong.",
      resultHint: "Không tìm thấy phần tử khớp selector vẫn trả success (found: false) — không làm workflow fail. Xem kết quả ở '{{steps.<label>.value}}'.",
    },
    getSchedules: {
      timezonePrefix: 'Lấy lịch trình hôm nay · múi giờ:',
    },
    wait: {
      durationLabel: 'Duration',
      unitLabel: 'Unit',
      durationPlaceholder: '5',
      unitSeconds: 'Seconds',
      unitMinutes: 'Minutes',
      unitHours: 'Hours',
    },
    condition: {
      variableLabel: 'Variable',
      variablePlaceholder: 'e.g. {{steps.NODE_ID.result}}',
      variableHint: 'Use template variable syntax',
      operatorLabel: 'Operator',
      valueLabel: 'Value',
      valuePlaceholder: 'Value to compare against',
      valueHint: 'Supports template variables',
      operators: {
        equals: 'Equals (==)',
        notEquals: 'Not Equals (!=)',
        contains: 'Contains',
        greaterThan: 'Greater Than (>)',
        lessThan: 'Less Than (<)',
        isEmpty: 'Is Empty',
      },
    },
    templateHelper: {
      insertLabel: 'Insert template variable',
      triggerGroup: 'Trigger',
      prevStepsGroup: 'Previous Steps',
    },
  },

  // ── Node types (labels shown in palette) ──
  nodeTypes: {
    'trigger.manual': 'Manual',
    'trigger.schedule': 'Schedule',
    'trigger.webhook': 'Webhook',
    'trigger.internal_event': 'Internal Event',
    'action.send_notification': 'Send Notification',
    'action.create_note': 'Create Note',
    'action.schedule': 'Create Schedule',
    'action.condition': 'Condition',
    'action.wait': 'Wait',
    'action.update_note': 'Update Note',
    'action.call_ai': 'Call AI',
    'action.call_api': 'Call API',
    'action.extract_html': 'Extract HTML',
    'action.get_schedules': 'Get Schedules',
    'action.create_task': 'Create Task',
    'action.update_task': 'Update Task',
  },
} as const

export type Strings = typeof strings

export function t(path: string): string
export function t(path: string, ...args: unknown[]): string
export function t(path: string, ...args: unknown[]): string {
  const parts = path.split('.')
  let current: unknown = strings
  for (const part of parts) {
    if (current && typeof current === 'object' && part in current) {
      current = (current as Record<string, unknown>)[part]
    } else {
      return path
    }
  }
  if (typeof current === 'function') {
    return (current as (...a: unknown[]) => string)(...args)
  }
  if (typeof current === 'string') {
    return current
  }
  return path
}

export function tf(path: string, ...args: unknown[]): string {
  return t(path, ...args)
}
