/* Keep uncertain writes identifiable when a user retries after a lost response. */
function createDomovoyClient({fetchImpl = (...args) => fetch(...args), uuid = () => crypto.randomUUID(), timeoutMs = 15000} = {}) {
  const uncertain = new Map();
  return async function request(path, {body = null, identity = '', headers = {}} = {}) {
    const key = body ? JSON.stringify([identity, path, body]) : null;
    let payload = null;
    if (body) {
      payload = uncertain.get(key);
      if (!payload) {
        payload = {...body, request_id: uuid()};
        uncertain.set(key, payload);
      }
    }
    for (let attempt = 0; attempt < 2; attempt++) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const response = await fetchImpl(path, {
          method: body ? 'POST' : 'GET', signal: controller.signal,
          headers: {...headers, ...(body ? {'Content-Type': 'application/json'} : {})},
          ...(body ? {body: JSON.stringify(payload)} : {})
        });
        let result;
        try { result = await response.json(); }
        catch { throw new Error('invalid-response'); }
        if (response.ok) {
          if (body) uncertain.delete(key);
          return result;
        }
        if (response.status >= 400 && response.status < 500 && response.status !== 408) {
          if (body) uncertain.delete(key);
          const error = new Error(result.error || 'Не удалось выполнить действие');
          error.definitive = true;
          throw error;
        }
        throw new Error('server-unavailable');
      } catch (error) {
        if (error.definitive) throw error;
        if (attempt === 1) throw new Error(body
          ? 'Ответ сервера не получен. Повторите отправку, не меняя поля и не перезагружая страницу: повтор не создаст вторую запись.'
          : 'Не удалось загрузить данные. Проверьте подключение и повторите попытку.');
      } finally { clearTimeout(timer); }
    }
  };
}
if (typeof module !== 'undefined' && module.exports) module.exports = {createDomovoyClient};
