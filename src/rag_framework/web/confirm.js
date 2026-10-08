// Accessible in-page confirmation; embedded browsers may disable native dialogs.
export function askConfirmation({title = '确认操作', message, input = false, confirmLabel = '确认', placeholder = ''}) {
  return new Promise(resolve => {
    const dialog = document.createElement('dialog'); dialog.className = 'confirmation-dialog';
    const heading = document.createElement('h2'); heading.textContent = title;
    const description = document.createElement('p'); description.textContent = message;
    const field = document.createElement('input'); field.hidden = !input;
    field.placeholder = placeholder; field.setAttribute('aria-label', title);
    const actions = document.createElement('div'); actions.className = 'dialog-actions';
    const cancel = document.createElement('button'); cancel.textContent = '取消';
    const accept = document.createElement('button'); accept.textContent = confirmLabel; accept.className = 'primary';
    let result = null;
    cancel.onclick = () => dialog.close();
    accept.onclick = () => {
      if (input && !field.value.trim()) { field.focus(); return; }
      result = input ? field.value : true; dialog.close();
    };
    field.onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); accept.click(); } };
    actions.append(cancel, accept); dialog.append(heading, description, field, actions);
    dialog.addEventListener('close', () => { dialog.remove(); resolve(result); }, {once: true});
    document.body.append(dialog); dialog.showModal();
    (input ? field : cancel).focus();
  });
}
