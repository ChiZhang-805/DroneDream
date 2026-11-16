//! A native, owned menu strip occupies the leading part of the system caption.
//! The owning window keeps its task-switcher title, DWM buttons and snap behavior.
use std::{
    cell::Cell,
    mem::size_of,
    ptr::{null, null_mut},
};
use tauri::{Emitter, WebviewWindow};
use windows_sys::Win32::{
    Graphics::Gdi::{
        CreatePen, GetStockObject, GetSysColor, GetSysColorBrush, LineTo, MoveToEx, RoundRect,
        SelectObject, COLOR_GRAYTEXT, COLOR_HIGHLIGHT, COLOR_HIGHLIGHTTEXT, COLOR_MENUTEXT,
        NULL_BRUSH, PS_SOLID,
    },
    UI::{
        Accessibility::{MSAAMENUINFO, MSAA_MENU_SIG},
        Controls::{
            DRAWITEMSTRUCT, MEASUREITEMSTRUCT, ODS_DISABLED, ODS_GRAYED, ODS_HOTLIGHT,
            ODS_SELECTED, ODT_MENU,
        },
    },
};
use windows_sys::{
    w,
    Win32::{
        Foundation::{HWND, LPARAM, LRESULT, POINT, RECT, WPARAM},
        Graphics::Gdi::{
            ClientToScreen, CreateSolidBrush, DeleteObject, FillRect, InvalidateRect, HBRUSH,
        },
        UI::{
            HiDpi::{GetDpiForWindow, GetSystemMetricsForDpi},
            Input::KeyboardAndMouse::{
                SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP, VK_CONTROL,
            },
            Shell::{DefSubclassProc, RemoveWindowSubclass, SetWindowSubclass},
            WindowsAndMessaging::*,
        },
    },
};

const BAR: windows_sys::core::PCWSTR = w!("DroneDream.CaptionMenu");
const APPLY_PENDING: u32 = WM_APP + 1;
const BACK: usize = 101;
const FORWARD: usize = 102;
const SIDEBAR: usize = 103;
const SETTINGS: usize = 104;
const CLOSE: usize = 105;
const ABOUT: usize = 106;

#[derive(Clone, Copy, Default, PartialEq, Eq, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct MenuState {
    chinese: bool,
    can_back: bool,
    can_forward: bool,
    can_sidebar: bool,
    sidebar_hidden: bool,
    can_settings: bool,
}

struct Strip {
    send_action: Box<dyn Fn(&str)>,
    icon_names: [MSAAMENUINFO; 6],
    brush: Cell<HBRUSH>,
    state: Cell<MenuState>,
    tracking: Cell<bool>,
    pending: Cell<Option<MenuState>>,
}

impl Strip {
    fn new(send_action: Box<dyn Fn(&str)>, brush: HBRUSH) -> Self {
        let icon_names = [
            "Back",
            "Forward",
            "Toggle Sidebar",
            "后退",
            "前进",
            "切换侧栏",
        ]
        .map(|text| {
            let ptr = match text {
                "Back" => w!("Back"),
                "Forward" => w!("Forward"),
                "Toggle Sidebar" => w!("Toggle Sidebar"),
                "后退" => w!("后退"),
                "前进" => w!("前进"),
                _ => w!("切换侧栏"),
            };
            MSAAMENUINFO {
                dwMSAASignature: MSAA_MENU_SIG as u32,
                cchWText: text.encode_utf16().count() as u32,
                pszWText: ptr.cast_mut(),
            }
        });
        Self {
            send_action,
            state: Cell::new(MenuState::default()),
            tracking: Cell::new(false),
            pending: Cell::new(None),
            brush: Cell::new(brush),
            icon_names,
        }
    }
}

// Reserve the system menu's normal line height. Draw the three line icons in
// device pixels, keeping menu highlight, disabled states and accessible names.
unsafe fn draw_icon(hwnd: HWND, draw: &DRAWITEMSTRUCT, brush: HBRUSH) {
    let r = draw.rcItem;
    let hot = draw.itemState & (ODS_SELECTED | ODS_HOTLIGHT) != 0;
    let disabled = draw.itemState & (ODS_DISABLED | ODS_GRAYED) != 0;
    FillRect(
        draw.hDC,
        &r,
        if hot {
            GetSysColorBrush(COLOR_HIGHLIGHT)
        } else {
            brush
        },
    );
    let ink = GetSysColor(if disabled {
        COLOR_GRAYTEXT
    } else if hot {
        COLOR_HIGHLIGHTTEXT
    } else {
        COLOR_MENUTEXT
    });
    let dpi = GetDpiForWindow(hwnd) as i32;
    let px = |n: i32| (n * dpi + 48) / 96;
    let cx = (r.left + r.right) / 2;
    let cy = (r.top + r.bottom) / 2;
    let pen = CreatePen(PS_SOLID, px(1).max(1), ink);
    let old_pen = SelectObject(draw.hDC, pen);
    let old_brush = SelectObject(draw.hDC, GetStockObject(NULL_BRUSH));
    let line = |x, y, x2, y2| {
        MoveToEx(draw.hDC, x, y, null_mut());
        LineTo(draw.hDC, x2, y2);
    };
    match draw.itemID as usize {
        SIDEBAR => {
            RoundRect(
                draw.hDC,
                cx - px(7),
                cy - px(6),
                cx + px(7) + 1,
                cy + px(6) + 1,
                px(4),
                px(4),
            );
            line(cx - px(2), cy - px(6), cx - px(2), cy + px(6));
        }
        id => {
            let dir = if id == BACK { -1 } else { 1 };
            let tip = cx + dir * px(6);
            line(cx - dir * px(6), cy, tip, cy);
            line(tip - dir * px(5), cy - px(5), tip, cy);
            line(tip, cy, tip - dir * px(5), cy + px(5));
        }
    }
    SelectObject(draw.hDC, old_brush);
    SelectObject(draw.hDC, old_pen);
    DeleteObject(pen);
}

fn wide(label: &str) -> Vec<u16> {
    label.encode_utf16().chain(Some(0)).collect()
}

unsafe fn item(menu: HMENU, flags: u32, id: usize, label: &str) {
    AppendMenuW(menu, flags, id, wide(label).as_ptr());
}

unsafe fn make_menu(s: MenuState, strip: &Strip) -> HMENU {
    let label = |en, zh| if s.chinese { zh } else { en };
    let root = CreateMenu();
    for (index, id) in [BACK, FORWARD, SIDEBAR].into_iter().enumerate() {
        let info = &strip.icon_names[index + if s.chinese { 3 } else { 0 }];
        AppendMenuW(root, MF_OWNERDRAW, id, std::ptr::from_ref(info).cast());
    }
    let file = CreatePopupMenu();
    item(file, MF_STRING, SETTINGS, label("&Settings…", "设置(&S)…"));
    item(
        file,
        MF_STRING,
        CLOSE,
        label("&Close Window\tAlt+F4", "关闭窗口(&C)\tAlt+F4"),
    );
    let edit = CreatePopupMenu();
    for (key, en, zh) in [
        (b'Z', "&Undo\tCtrl+Z", "撤销(&U)\tCtrl+Z"),
        (b'Y', "&Redo\tCtrl+Y", "重做(&R)\tCtrl+Y"),
        (b'X', "Cu&t\tCtrl+X", "剪切(&T)\tCtrl+X"),
        (b'C', "&Copy\tCtrl+C", "复制(&C)\tCtrl+C"),
        (b'V', "&Paste\tCtrl+V", "粘贴(&P)\tCtrl+V"),
        (b'A', "Select &All\tCtrl+A", "全选(&A)\tCtrl+A"),
    ] {
        if key == b'X' {
            AppendMenuW(edit, MF_SEPARATOR, 0, null());
        }
        item(edit, MF_STRING, key as usize, label(en, zh));
    }
    let view = CreatePopupMenu();
    item(view, MF_STRING, BACK, label("&Back", "后退(&B)"));
    item(view, MF_STRING, FORWARD, label("&Forward", "前进(&F)"));
    item(
        view,
        MF_STRING,
        SIDEBAR,
        if s.sidebar_hidden {
            label("&Show Sidebar", "显示侧栏(&S)")
        } else {
            label("&Hide Sidebar", "收起侧栏(&S)")
        },
    );
    let help = CreatePopupMenu();
    item(
        help,
        MF_STRING,
        ABOUT,
        label("&About DroneDream", "关于 DroneDream(&A)"),
    );
    for (menu, en, zh) in [
        (file, "&File", "文件(&F)"),
        (edit, "&Edit", "编辑(&E)"),
        (view, "&View", "视图(&V)"),
        (help, "&Help", "帮助(&H)"),
    ] {
        item(root, MF_POPUP, menu as usize, label(en, zh));
    }
    for (menu, id, enabled) in [
        (file, SETTINGS, s.can_settings),
        (view, BACK, s.can_back),
        (view, FORWARD, s.can_forward),
        (view, SIDEBAR, s.can_sidebar),
    ] {
        EnableMenuItem(
            menu,
            id as u32,
            if enabled { MF_ENABLED } else { MF_GRAYED },
        );
    }
    for (pos, enabled) in [s.can_back, s.can_forward, s.can_sidebar]
        .into_iter()
        .enumerate()
    {
        EnableMenuItem(
            root,
            pos as u32,
            MF_BYPOSITION | if enabled { MF_ENABLED } else { MF_GRAYED },
        );
    }
    root
}

unsafe fn paint_menu(bar: HWND, brush: HBRUSH) {
    let info = MENUINFO {
        cbSize: size_of::<MENUINFO>() as u32,
        fMask: MIM_BACKGROUND,
        hbrBack: brush,
        ..Default::default()
    };
    SetMenuInfo(GetMenu(bar), &info);
    DrawMenuBar(bar);
    InvalidateRect(bar, null(), 1);
}

unsafe fn place(owner: HWND, bar: HWND) {
    if IsWindowVisible(owner) == 0
        || IsIconic(owner) != 0
        || GetWindowLongW(owner, GWL_STYLE) as u32 & WS_CAPTION != WS_CAPTION
    {
        ShowWindow(bar, SW_HIDE);
        return;
    }
    let dpi = GetDpiForWindow(owner);
    let height = GetSystemMetricsForDpi(SM_CYCAPTION, dpi);
    let mut origin = POINT::default();
    ClientToScreen(owner, &mut origin);
    let mut last = RECT::default();
    let mut first = RECT::default();
    let menu = GetMenu(bar);
    // The host starts wide so Windows lays out all seven items on one line.
    if GetMenuItemRect(bar, menu, 0, &mut first) == 0
        || GetMenuItemRect(bar, menu, 6, &mut last) == 0
    {
        return;
    }
    let width = last.right - first.left + 8 * (dpi as i32) / 96;
    SetWindowPos(
        bar,
        null_mut(),
        origin.x,
        origin.y - height,
        width,
        height,
        SWP_NOACTIVATE | SWP_NOZORDER | SWP_SHOWWINDOW,
    );
}

unsafe extern "system" fn owner_proc(
    hwnd: HWND,
    msg: u32,
    w: WPARAM,
    l: LPARAM,
    id: usize,
    bar: usize,
) -> LRESULT {
    let bar = bar as HWND;
    if msg == WM_NCDESTROY {
        RemovePropW(hwnd, BAR);
        RemoveWindowSubclass(hwnd, Some(owner_proc), id);
        return DefSubclassProc(hwnd, msg, w, l);
    }
    let result = DefSubclassProc(hwnd, msg, w, l);
    if msg == WM_ENABLE && IsWindow(bar) != 0 {
        windows_sys::Win32::UI::Input::KeyboardAndMouse::EnableWindow(bar, (w != 0) as i32);
    }
    if matches!(
        msg,
        WM_WINDOWPOSCHANGED | WM_DPICHANGED | WM_SHOWWINDOW | WM_STYLECHANGED
    ) && IsWindow(bar) != 0
    {
        place(hwnd, bar);
    }
    result
}

// Use the same editing shortcuts as the native Windows Edit menu. Give focus
// back to our owner before issuing a shortcut, including when its menu had focus.
unsafe fn edit_shortcut(owner: HWND, key: u16) {
    if GetForegroundWindow() != owner {
        SetForegroundWindow(owner);
        if GetForegroundWindow() != owner {
            return;
        }
    }
    let input = |vk, flags| INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: vk,
                dwFlags: flags,
                ..Default::default()
            },
        },
    };
    let keys = [
        input(VK_CONTROL, 0),
        input(key, 0),
        input(key, KEYEVENTF_KEYUP),
        input(VK_CONTROL, KEYEVENTF_KEYUP),
    ];
    SendInput(keys.len() as u32, keys.as_ptr(), size_of::<INPUT>() as i32);
}

unsafe extern "system" fn bar_proc(
    hwnd: HWND,
    msg: u32,
    w: WPARAM,
    l: LPARAM,
    id: usize,
    data: usize,
) -> LRESULT {
    let strip = &*(data as *const Strip);
    let owner = GetWindow(hwnd, GW_OWNER);
    match msg {
        WM_MEASUREITEM => {
            let m = &mut *(l as *mut MEASUREITEMSTRUCT);
            if m.CtlType == ODT_MENU && (BACK..=SIDEBAR).contains(&(m.itemID as usize)) {
                m.itemWidth = 22 * GetDpiForWindow(hwnd) / 96;
                m.itemHeight = GetSystemMetricsForDpi(SM_CYMENU, GetDpiForWindow(hwnd)) as u32;
                return 1;
            }
        }
        WM_DRAWITEM => {
            let d = &*(l as *const DRAWITEMSTRUCT);
            if d.CtlType == ODT_MENU && (BACK..=SIDEBAR).contains(&(d.itemID as usize)) {
                draw_icon(hwnd, d, strip.brush.get());
                return 1;
            }
        }
        WM_ENTERMENULOOP => strip.tracking.set(true),
        WM_EXITMENULOOP => {
            strip.tracking.set(false);
            if strip.pending.get().is_some() {
                PostMessageW(hwnd, APPLY_PENDING, 0, 0);
            }
        }
        APPLY_PENDING => {
            if let Some(state) = strip.pending.take() {
                update_menu(owner, state);
            }
            return 0;
        }
        WM_MOUSEACTIVATE => return MA_NOACTIVATE as isize,
        WM_ERASEBKGND => {
            let mut r = RECT::default();
            GetClientRect(hwnd, &mut r);
            FillRect(w as _, &r, strip.brush.get());
            return 1;
        }
        WM_COMMAND => {
            let command = w & 0xffff;
            match command {
                BACK | FORWARD | SIDEBAR | SETTINGS => {
                    let name = match command {
                        BACK => "back",
                        FORWARD => "forward",
                        SIDEBAR => "sidebar",
                        _ => "settings",
                    };
                    (strip.send_action)(name);
                }
                CLOSE => {
                    PostMessageW(owner, WM_CLOSE, 0, 0);
                }
                ABOUT => {
                    let title = if strip.state.get().chinese {
                        "关于 DroneDream"
                    } else {
                        "About DroneDream"
                    };
                    let mut name = [0u16; 128];
                    let count = GetWindowTextW(owner, name.as_mut_ptr(), name.len() as i32);
                    let edition = String::from_utf16_lossy(&name[..count as usize]);
                    let details = format!(
                        "{}\n{} · Build {}",
                        edition,
                        env!("CARGO_PKG_VERSION"),
                        env!("DRONEDREAM_BUILD_NUMBER")
                    );
                    MessageBoxW(
                        owner,
                        wide(&details).as_ptr(),
                        wide(title).as_ptr(),
                        MB_OK | MB_ICONINFORMATION,
                    );
                }
                65 | 67 | 86 | 88 | 89 | 90 => edit_shortcut(owner, command as u16),
                _ => {}
            }
            return 0;
        }
        WM_NCDESTROY => {
            RemoveWindowSubclass(hwnd, Some(bar_proc), id);
            if GetPropW(owner, BAR) == hwnd {
                RemovePropW(owner, BAR);
            }
            let brush = strip.brush.get();
            let result = DefSubclassProc(hwnd, msg, w, l);
            DeleteObject(brush);
            drop(Box::from_raw(data as *mut Strip));
            return result;
        }
        _ => {}
    }
    DefSubclassProc(hwnd, msg, w, l)
}

pub(crate) fn attach(window: &WebviewWindow) -> Result<(), String> {
    let owner = window.hwnd().map_err(|e| e.to_string())?.0.cast();
    let sender = window.clone();
    unsafe {
        attach_to(
            owner,
            Box::new(move |action| {
                let _ = sender.emit("caption-action", action);
            }),
        )
    }
}

unsafe fn attach_to(owner: HWND, send_action: Box<dyn Fn(&str)>) -> Result<(), String> {
    {
        let state = MenuState::default();
        // An owned tool window groups with the workspace in the z-order and is
        // automatically destroyed with it. Its menu remains a real Win32 HMENU.
        let class = w!("DroneDreamCaptionMenu");
        let instance = windows_sys::Win32::System::LibraryLoader::GetModuleHandleW(null());
        let wc = WNDCLASSW {
            hInstance: instance,
            lpfnWndProc: Some(DefWindowProcW),
            lpszClassName: class,
            ..Default::default()
        };
        RegisterClassW(&wc);
        let bar = CreateWindowExW(
            WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            class,
            w!("DroneDream menu"),
            WS_POPUP,
            0,
            0,
            640,
            32,
            owner,
            null_mut(),
            instance,
            null(),
        );
        if bar.is_null() {
            return Err(std::io::Error::last_os_error().to_string());
        }
        let brush = CreateSolidBrush(0xffffff);
        let data = Box::into_raw(Box::new(Strip::new(send_action, brush)));
        if SetWindowSubclass(bar, Some(bar_proc), 1, data as usize) == 0 {
            drop(Box::from_raw(data));
            DeleteObject(brush);
            DestroyWindow(bar);
            return Err("Could not attach caption menu".into());
        }
        SetWindowLongPtrW(bar, GWLP_USERDATA, data as isize);
        if SetPropW(owner, BAR, bar) == 0
            || SetWindowSubclass(owner, Some(owner_proc), 1, bar as usize) == 0
        {
            RemovePropW(owner, BAR);
            DestroyWindow(bar);
            return Err("Could not track caption menu".into());
        }
        let menu = make_menu(state, &*data);
        if SetMenu(bar, menu) == 0 {
            DestroyMenu(menu);
            DestroyWindow(bar);
            return Err("Could not initialize caption commands".into());
        }
        paint_menu(bar, brush);
        place(owner, bar);
    }
    Ok(())
}

unsafe fn strip_for(owner: HWND) -> Option<(HWND, *const Strip)> {
    let bar = GetPropW(owner, BAR) as HWND;
    if bar.is_null() {
        return None;
    }
    let data = GetWindowLongPtrW(bar, GWLP_USERDATA);
    if data == 0 {
        return None;
    }
    Some((bar, data as *const Strip))
}

pub(crate) unsafe fn color(owner: HWND, value: u32) {
    if let Some((bar, data)) = strip_for(owner) {
        let strip = &*data;
        let next = CreateSolidBrush(value);
        if !next.is_null() {
            let old = strip.brush.replace(next);
            paint_menu(bar, next);
            DeleteObject(old);
        }
    }
}

unsafe fn update_menu(owner: HWND, state: MenuState) {
    if let Some((bar, strip)) = strip_for(owner) {
        let strip = &*strip;
        if strip.tracking.get() {
            strip.pending.set(Some(state));
            return;
        }
        if strip.state.get() == state {
            return;
        }
        let old = GetMenu(bar);
        let next = make_menu(state, strip);
        if SetMenu(bar, next) != 0 {
            strip.state.set(state);
            DestroyMenu(old);
            // Allow a longer translation to lay out before measuring it.
            SetWindowPos(
                bar,
                null_mut(),
                0,
                0,
                640 * GetDpiForWindow(bar) as i32 / 96,
                32,
                SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOZORDER,
            );
            paint_menu(bar, strip.brush.get());
            place(owner, bar);
        } else {
            DestroyMenu(next);
        }
    }
}

#[tauri::command]
pub(crate) fn configure_caption_menu(
    window: WebviewWindow,
    state: MenuState,
) -> Result<(), String> {
    let own = window.clone();
    window
        .run_on_main_thread(move || unsafe {
            let Ok(hwnd) = own.hwnd() else { return };
            update_menu(hwnd.0.cast(), state);
        })
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub(crate) fn focus_caption_menu(window: WebviewWindow, mnemonic: String) -> Result<(), String> {
    let key = match mnemonic.as_str() {
        "file" => b'f',
        "edit" => b'e',
        "view" => b'v',
        "help" => b'h',
        _ => return Ok(()),
    };
    let own = window.clone();
    window
        .run_on_main_thread(move || unsafe {
            if let Ok(hwnd) = own.hwnd() {
                let bar = GetPropW(hwnd.0.cast(), BAR) as HWND;
                if !bar.is_null() {
                    PostMessageW(bar, WM_SYSCOMMAND, SC_KEYMENU as usize, key as isize);
                }
            }
        })
        .map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::rc::Rc;

    #[test]
    fn caption_tracks_the_decorated_owner_and_dispatches_localized_commands() {
        unsafe {
            let owner = CreateWindowExW(
                WS_EX_TOOLWINDOW,
                w!("STATIC"),
                w!("Window test"),
                WS_OVERLAPPEDWINDOW,
                -4000,
                -3000,
                980,
                700,
                null_mut(),
                null_mut(),
                null_mut(),
                null(),
            );
            assert!(!owner.is_null());
            let received = Rc::new(std::cell::RefCell::new(Vec::new()));
            let out = received.clone();
            attach_to(
                owner,
                Box::new(move |item| out.borrow_mut().push(item.to_owned())),
            )
            .unwrap();
            ShowWindow(owner, SW_SHOWNOACTIVATE);
            let bar = GetPropW(owner, BAR) as HWND;
            assert_eq!(GetWindow(bar, GW_OWNER), owner);
            assert_eq!(
                GetWindowLongW(owner, GWL_STYLE) as u32 & WS_OVERLAPPEDWINDOW,
                WS_OVERLAPPEDWINDOW
            );
            let menu = GetMenu(bar);
            assert_eq!(GetMenuItemCount(menu), 7);
            assert!(GetMenuState(menu, 0, MF_BYPOSITION) & MF_GRAYED != 0);
            let mut title = [0u16; 32];
            let len = GetMenuStringW(menu, 3, title.as_mut_ptr(), 32, MF_BYPOSITION);
            assert_eq!(String::from_utf16_lossy(&title[..len as usize]), "&File");
            update_menu(
                owner,
                MenuState {
                    chinese: true,
                    can_settings: true,
                    can_back: true,
                    can_sidebar: true,
                    ..Default::default()
                },
            );
            let menu = GetMenu(bar);
            let len = GetMenuStringW(menu, 3, title.as_mut_ptr(), 32, MF_BYPOSITION);
            assert_eq!(String::from_utf16_lossy(&title[..len as usize]), "文件(&F)");
            SetWindowPos(
                owner,
                null_mut(),
                -3800,
                -2700,
                1000,
                720,
                SWP_NOACTIVATE | SWP_NOZORDER,
            );
            let mut br = RECT::default();
            GetWindowRect(bar, &mut br);
            let mut origin = POINT::default();
            ClientToScreen(owner, &mut origin);
            assert_eq!((br.left, br.bottom), (origin.x, origin.y));
            assert_ne!(IsWindowVisible(bar), 0);
            let mut last = RECT::default();
            assert_ne!(GetMenuItemRect(bar, menu, 6, &mut last), 0);
            assert!(last.right <= br.right && last.top >= br.top && last.bottom <= br.bottom);
            let x = (last.right + last.left) / 2;
            let y = (last.bottom + last.top) / 2;
            let lp = (((y as u32 & 0xffff) << 16) | (x as u32 & 0xffff)) as LPARAM;
            assert_eq!(SendMessageW(bar, WM_NCHITTEST, 0, lp), HTMENU as LRESULT);
            SendMessageW(bar, WM_COMMAND, SETTINGS, 0);
            assert_eq!(*received.borrow(), ["settings"]);
            ShowWindow(owner, SW_MINIMIZE);
            assert_eq!(IsWindowVisible(bar), 0);
            DestroyWindow(owner);
            assert_eq!(IsWindow(bar), 0);
        }
    }
}
