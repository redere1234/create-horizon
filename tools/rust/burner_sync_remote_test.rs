// Test-only control of the normal Remote lifecycle field. The production
// predicate, packet receiver and cache cleanup remain the actual mod code.
#[cfg(test)]
impl Game<'_> {
    pub(in crate::game) fn create_burner_sync_test_level(&mut self, dimension: Option<&str>) {
        self.remote.as_mut().unwrap().heard_level = dimension.map(str::to_owned);
    }
}
