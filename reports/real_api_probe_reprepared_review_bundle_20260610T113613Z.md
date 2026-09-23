# Real API Probe Manual Review Bundle

- Frozen output root: `outputs/llm_generation_real_api_probe_reprepared_20260610T113535Z`
- Probe result JSON: `not_applicable`
- Existing manual review CSV: `not_found`
- Record count: `5`
- mock_only: `True`
- real_generation_pending: `True`

## Review Instructions

This bundle is for human review only. Do not treat automatic checks as human judgment.

Common checks:
- Is the output a single-line commit subject?
- Is it faithful to the diff and original commit message?
- Does it omit any major independent change?
- Does it assert behavior, motive, or effect that the diff does not support?

Category-specific focus:
- `atomic_simple / G1`: check whether the output captures the single main change and does not over-promote supporting tests.
- `hard_b / G1`: check whether complex but single-purpose edits stay compressed into one purpose without fake splitting.
- `synthetic_multi / G4`: check whether both intents are covered and whether retrieval examples appear relevant.
- `synthetic_multi / G5`: compare against G4 for completeness and faithfulness; check whether the model copies the oracle plan mechanically.
- `M_real_multi / G4`: check whether the output over-infers unstated motivation or effect from the diff alone.

Special attention:
- For `Refactor ComponentBase internals and flatten Surface cell storage for ABI stability`, verify whether `for ABI stability` is supported by diff or original message evidence.

## Record 1

- Sample ID: `atomic_simple:eb8a30b8079b8d73`
- Category: `atomic_simple`
- Strategy: `G1`
- Repo: `camunda/zeebe`
- Repo canonical: `camunda/zeebe`
- Repo parse status: `github_slug`
- SHA: `448964457e06c088df68d78cf10cdbcde971530e`
- Generated subject: `Update implementation based on diff`
- Reference subject: `test(engine): added signal events deployment tests`

### Original Commit Message

```text
test(engine): added signal events deployment tests
```

### Prompt Metadata

- Prompt chars: `11800`
- Estimated prompt tokens: `2950`
- Status: `generated`
- Thinking mode: `disabled`
- Latency ms: `0`
- Usage: `{'prompt_chars': 11800, 'completion_chars': 35}`

### Automatic Format Checks

- Non-empty: `True`
- Single line: `True`
- Subject length chars: `35`
- Subject length tokens: `5`
- Artifact markers present: `False`

### Diff Excerpt

- Excerpted: `False`
```diff
diff --git a/engine/src/test/java/io/camunda/zeebe/engine/processing/deployment/model/validation/SignalEventValidationTest.java b/engine/src/test/java/io/camunda/zeebe/engine/processing/deployment/model/validation/SignalEventValidationTest.java
new file mode 100644
index 00000000000..9ab7a439801
--- /dev/null
+++ b/engine/src/test/java/io/camunda/zeebe/engine/processing/deployment/model/validation/SignalEventValidationTest.java
@@ -0,0 +1,290 @@
+/*
+ * Copyright Camunda Services GmbH and/or licensed to Camunda Services GmbH under
+ * one or more contributor license agreements. See the NOTICE file distributed
+ * with this work for additional information regarding copyright ownership.
+ * Licensed under the Zeebe Community License 1.1. You may not use this file
+ * except in compliance with the Zeebe Community License 1.1.
+ */
+package io.camunda.zeebe.engine.processing.deployment.model.validation;
+
+import static org.assertj.core.api.Assertions.assertThat;
+
+import io.camunda.zeebe.engine.util.EngineRule;
+import io.camunda.zeebe.model.bpmn.Bpmn;
+import io.camunda.zeebe.model.bpmn.BpmnModelInstance;
+import io.camunda.zeebe.model.bpmn.builder.ProcessBuilder;
+import io.camunda.zeebe.model.bpmn.instance.zeebe.ZeebeTaskDefinition;
+import io.camunda.zeebe.protocol.record.Assertions;
+import io.camunda.zeebe.protocol.record.ExecuteCommandResponseDecoder;
+import io.camunda.zeebe.protocol.record.Record;
+import io.camunda.zeebe.protocol.record.RecordType;
+import io.camunda.zeebe.protocol.record.RejectionType;
+import io.camunda.zeebe.protocol.record.intent.DeploymentIntent;
+import io.camunda.zeebe.protocol.record.value.DeploymentRecordValue;
+import io.camunda.zeebe.test.util.Strings;
+import io.camunda.zeebe.test.util.record.RecordingExporterTestWatcher;
+import org.junit.ClassRule;
+import org.junit.Rule;
+import org.junit.Test;
+
+public final class SignalEventValidationTest {
+
+  @ClassRule public static final EngineRule engine = EngineRule.singlePartition();
+
+  @Rule
+  public final RecordingExporterTestWatcher recordingExporterTestWatcher =
+      new RecordingExporterTestWatcher();
+
+  @Test
+  public void shouldDeploySignalStartEvent() {
+    // given
+    final String processId = Strings.newRandomValidBpmnId();
+
+    // when
+    final BpmnModelInstance processDefinition =
+        Bpmn.createExecutableProcess(processId).startEvent("start").signal("signalName").done();
+
+    final Record<DeploymentRecordValue> deployment =
+        engine.deployment().withXmlResource(processDefinition).deploy();
+
+    // then
+    assertThat(deployment.getKey())
+        .describedAs("Support signal start event process deployment")
+        .isNotNegative();
+  }
+
+  @Test
+  public void shouldDeploySignalEndEvent() {
+    // given
+    final String processId = Strings.newRandomValidBpmnId();
+
+    // when
+    final BpmnModelInstance processDefinition =
+        Bpmn.createExecutableProcess(processId)
+            .startEvent("start")
+            .endEvent()
+            .addExtensionElement(ZeebeTaskDefinition.class, b -> b.setType("type"))
+            .signalEventDefinition()
+            .done();
+
+    final Record<DeploymentRecordValue> deployment =
+        engine.deployment().withXmlResource(processDefinition).deploy();
+
+    // then
+    assertThat(deployment.getKey())
+        .describedAs("Support signal end event process deployment")
+        .isNotNegative();
+  }
+
+  @Test
+  public void shouldDeploySignalThrowEvent() {
+    // given
+    final String processId = Strings.newRandomValidBpmnId();
+
+    // when
+    final BpmnModelInstance processDefinition =
+        Bpmn.createExecutableProcess(processId)
+            .startEvent("start")
+            .intermediateThrowEvent()
+            .addExtensionElement(ZeebeTaskDefinition.class, b -> b.setType("signalType"))
+            .signalEventDefinition()
+            .throwEventDefinitionDone()
+            .endEvent()
+            .done();
+
+    final Record<DeploymentRecordValue> deployment =
+        engine.deployment().withXmlResource(processDefinition).deploy();
+
+    // then
+    assertThat(deployment.getKey())
+        .describedAs("Support signal throw event process deployment")
+        .isNotNegative();
+  }
+
+  @Test
+  public void shouldDeployMultipleSignalStartEvents() {
+    // given
+    final BpmnModelInstance processDefinition = processWithMultipleSignalStartEvents();
+
+    // when
+    final Record<DeploymentRecordValue> deployment =
+        engine.deployment().withXmlResource(processDefinition).deploy();
+
+    // then
+    assertThat(deployment.getKey())
+        .describedAs("Support multiple signal star event process deployment")
+        .isNotNegative();
+  }
+
+  @Test
+  public void shouldDeploySignalBoundaryEvent() {
+    // given
+    final String processId = Strings.newRandomValidBpmnId();
+
+    // when
+    final BpmnModelInstance processDefinition =
+        Bpmn.createExecutableProcess(processId)
+            .startEvent()
+            .manualTask()
+            .boundaryEvent("boundary-1", b -> b.signal(m -> m.name("signalName")))
+            .endEvent()
+            .done();
+
+    final Record<DeploymentRecordValue> deployment =
+        engine.deployment().withXmlResource(processDefinition).deploy();
+
+    // then
+    assertThat(deployment.getKey())
+        .describedAs("Support signal boundary event process deployment")
+        .isNotNegative();
+  }
+
+  @Test
+  public void shouldDeploySignalStartAndMultipleBoundaryEvents() {
+    // given
+    final String processId = Strings.newRandomValidBpmnId();
+
+    // when
+    final BpmnModelInstance processDefinition =
+        Bpmn.createExecutableProcess(processId)
+            .startEvent()
+            .signal("start-signal")
+            .manualTask("task")
+            .boundaryEvent("boundary-1", b -> b.signal(m -> m.name("signalName1")))
+            .endEvent()
+            .moveToActivity("task")
+            .boundaryEvent("boundary-2", b -> b.signal(m -> m.name("signalName2")))
+            .endEvent()
+            .done();
+
+    final Record<DeploymentRecordValue> deployment =
+        engine.deployment().withXmlResource(processDefinition).deploy();
+
+    // then
+    assertThat(deployment.getKey())
+        .describedAs(
+            "Support signal start event and multiple signal boundary event process deployment")
+        .isNotNegative();
+  }
+
+  @Test
+  public void shouldDeployEventSubProcessWithMultipleSignalEvents() {
+    // given
+    final BpmnModelInstance processDefinition =
+        getEventSubProcessWithEmbeddedSubProcessWithBoundarySignalEvent();
+
+    // when
+    final Record<DeploymentRecordValue> deployment =
+        engine.deployment().withXmlResource(processDefinition).deploy();
+
+    // then
+    assertThat(deployment.getKey())
+        .describedAs(
+            "Support event sub process with signal start event and boundary event process deployment")
+        .isNotNegative();
+  }
+
+  @Test
+  public void shouldDeploySignalIntermediateCatchEvent() {
+    // given
+    final String processId = Strings.newRandomValidBpmnId();
+
+    // when
+    final BpmnModelInstance processDefinition =
+        Bpmn.createExecutableProcess(processId)
+            .startEvent()
+            .intermediateCatchEvent("foo")
+            .signal("signalName")
+            .done();
+
+    final Record<DeploymentRecordValue> deployment =
+        engine.deployment().withXmlResource(processDefinition).deploy();
+
+    // then
+    assertThat(deployment.getKey())
+        .describedAs("Support signal intermediate catch event process deployment")
+        .isNotNegative();
+  }
+
+  @Test
+  public void shouldDeploySignalStartAndBoundaryEventEvenWithSameSignal() {
+    // given
+    final String processId = Strings.newRandomValidBpmnId();
+
+    // when
+    final BpmnModelInstance processDefinition =
+        Bpmn.createExecutableProcess(processId)
+            .startEvent()
+            .signal(m -> m.id("start-signal").name("signalName"))
+            .manualTask()
+            .boundaryEvent("boundary-1", b -> b.signal(m -> m.name("signalName")))
+            .endEvent()
+            .done();
+
+    final Record<DeploymentRecordValue> deployment =
+        engine.deployment().withXmlResource(processDefinition).deploy();
+
+    // then
+    assertThat(deployment.getKey())
+        .describedAs(
+            "Support signal start and boundary event even with the same signal name process deployment")
+        .isNotNegative();
+  }
+
+  @Test
+  public void shouldRejectDeployMultipleStartEventsWithSameSignal() {
+    // given
+    final BpmnModelInstance processDefinition = getProcessWithMultipleStartEventsWithSameSignal();
+
+    final Record<DeploymentRecordValue> rejectedDeployment =
+        engine.deployment().withXmlResource(processDefinition).expectRejection().deploy();
+
+    // then
+    Assertions.assertThat(rejectedDeployment)
+        .hasKey(ExecuteCommandResponseDecoder.keyNullValue())
+        .hasRecordType(RecordType.COMMAND_REJECTION)
+        .hasIntent(DeploymentIntent.CREATE)
+        .hasRejectionType(RejectionType.INVALID_ARGUMENT);
+    assertThat(rejectedDeployment.getRejectionReason())
+        .contains("Element: process")
+        .contains(
+            "ERROR: Multiple signal event definitions with the same name 'signalName' are not allowed.");
+  }
+
+  private static BpmnModelInstance
+      getEventSubProcessWithEmbeddedSubProcessWithBoundarySignalEvent() {
+    final ProcessBuilder builder = Bpmn.createExecutableProcess("process");
+    builder
+        .eventSubProcess("event_sub_proc")
+        .startEvent(
+            "event_sub_start",
+            a -> a.signal(m -> m.id("event_sub_start_signal").name("signalName1")))
+        .subProcess(
+            "embedded",
+            s ->
+                s.boundaryEvent(
+                    "boundary-msg", b -> b.signal("signalName2").endEvent("boundary-end")))
+        .embeddedSubProcess()
+        .startEvent("embedded_sub_start")
+        .endEvent("embedded_sub_end")
+        .moveToNode("embedded")
+        .endEvent("event_sub_end");
+    return builder.startEvent("start").endEvent("end").done();
+  }
+
+  public static BpmnModelInstance processWithMultipleSignalStartEvents() {
+    final ProcessBuilder process = Bpmn.createExecutableProcess();
+    process.startEvent().signal("s1").endEvent();
+    process.startEvent().signal("s2").endEvent();
+    process.startEvent().signal(s -> s.nameExpression("signal_var")).endEvent();
+    return process.startEvent().signal("s3").endEvent().done();
+  }
+
+  private static BpmnModelInstance getProcessWithMultipleStartEventsWithSameSignal() {
+    final ProcessBuilder process = Bpmn.createExecutableProcess("processId");
+    final String signalName = "signalName";
+    process.startEvent("start1").signal(m -> m.id("start-signal").name(signalName)).endEvent();
+    process.startEvent("start2").signal(signalName).endEvent();
+    return process.done();
+  }
+}
```

### Human Review Questions

- Does the output match single-line commit subject format?
- Is it faithful to the diff and original message?
- Does it omit any major change?
- Does it hallucinate any unsupported behavior, motive, or effect?
- Does it accurately express one main change?
- Does it incorrectly elevate supporting test edits into the main goal?

## Record 2

- Sample ID: `hard_b:3366abdb796ceefc`
- Category: `hard_b`
- Strategy: `G1`
- Repo: `mongodb/mongoid`
- Repo canonical: `mongodb/mongoid`
- Repo parse status: `github_slug`
- SHA: `73c3afdf131235b89e4e73ce87b4640ead9cad88`
- Generated subject: `Update implementation based on diff`
- Reference subject: `MONGOID 5731 Add Criteria#eager_load method to use aggregation pipeline for eager loading (#6081)`

### Original Commit Message

```text
MONGOID 5731 Add Criteria#eager_load method to use aggregation pipeline for eager loading (#6081)

* Adds support for single hash input in nested attributes for has_many associations.

* Using $lookup for #eager_load

* add a forgotten comment

* removing unneeded check

* removing accidental change

* updating comment

* switching to only one query

* removing debugging

* Cleaning up code

* removing bug

* Switch how we approach querying to fix pipeline

* adding tests for to_pipeline_for_lookup

* Adding testing, including testing correct # of queries

* adding argument error

* Fixing error messages for eager_load

* adding @use_lookup to marshalable and criteria copy

* About to remove a lot of this - commit in case I decide this functionality actually is needed

* We no longer do lookup on embedded docs

* re-adding removed test

* using preload_for_lookup instead of preload

* Fixing marshalling errors

* moving private function to end of class

* Adding tests and trying to fix bugs shown by them

* Fixing bug with primary_key

* Only test on 5.0 and above

* Responding to automatic comments - trying to make code more readable

* adding buildable tests

* Adding benchmarking

* Removing default sort

* Addressing comments

* Fixing first() to allow nil, and adding default ordering
```

### Prompt Metadata

- Prompt chars: `72638`
- Estimated prompt tokens: `18159`
- Status: `generated`
- Thinking mode: `disabled`
- Latency ms: `0`
- Usage: `{'prompt_chars': 72638, 'completion_chars': 35}`

### Automatic Format Checks

- Non-empty: `True`
- Single line: `True`
- Subject length chars: `35`
- Subject length tokens: `5`
- Artifact markers present: `False`

### Diff Excerpt

- Excerpted: `True`
```diff
diff --git a/lib/mongoid/association/accessors.rb b/lib/mongoid/association/accessors.rb
--- a/lib/mongoid/association/accessors.rb
+++ b/lib/mongoid/association/accessors.rb
@@ -131,6 +131,10 @@ def get_relation(name, association, object, reload = false)
+              # Check if data was loaded via $lookup aggregation
+              elsif !association.embedded? && attributes.key?(name.to_s)
+                # Use the pre-loaded association data from $lookup
+                __build__(name, attributes[name.to_s], association)
@@ -223,7 +227,7 @@ def _mongoid_filter_selected_fields(assoc_key)
-            object._id == attributes[association.key]
+            object[association.try(:primary_key) || :_id] == attributes[association.key]
diff --git a/lib/mongoid/association/eager.rb b/lib/mongoid/association/eager.rb
--- a/lib/mongoid/association/eager.rb
+++ b/lib/mongoid/association/eager.rb
@@ -14,12 +14,18 @@ class Eager
+      # @param [ Boolean ] use_lookup Whether to use $lookup aggregation
+      #   for eager loading. This is used in Criteria#eager_load.
+      # @param [ Array<Hash> ] pipeline The aggregation pipeline to use
+      #   when using $lookup for eager loading.
-      def initialize(associations, docs)
+      def initialize(associations, docs, use_lookup = false, pipeline = [])
+        @use_lookup = use_lookup
+        @pipeline = pipeline
@@ -30,6 +36,13 @@ def initialize(associations, docs)
+
+        if @use_lookup
+          preload_with_lookup
+          @loaded = @docs
+          return @loaded.flatten
+        end
+
@@ -49,6 +62,21 @@ def preload
+      # Preload the current association using $lookup aggregation.
+      # This method executes the aggregation pipeline
+      # and instantiates the documents.
+      # @example Preload the current association using $lookup.
+      #   loader.preload_with_lookup
+      def preload_with_lookup
+        # For $lookup aggregation, execute pipeline and instantiate documents
+        owner_class = @associations.first.owner_class
+        aggregated_docs = owner_class.collection.aggregate(@pipeline)
+        aggregated_docs.each do |doc|
+          parsed_doc = Factory.from_db(owner_class, doc)
+          @docs << parsed_doc
+        end
+      end
+
@@ -69,10 +97,7 @@ def each_loaded_document(&block)
-        criteria = cls.criteria
-        criteria = criteria.apply_scope(@association.scope)
-        criteria = criteria.any_in(key => keys)
-        criteria.inclusions = criteria.inclusions - [@association]
+        criteria = prepare_criteria_for_loaded_documents(cls, keys)
@@ -155,6 +180,19 @@ def set_relation(doc, element)
+
+      # Prepares the criteria to retrieve the documents of the specified
+      # class, that have the foreign key included in the specified list of keys.
+      # When the documents are retrieved, the set of inclusions applied
+      # is the set of inclusions applied to the host document minus the
+      # association that is being eagerly loaded.
+      def prepare_criteria_for_loaded_documents(cls, keys)
+        criteria = cls.criteria
+        criteria = criteria.apply_scope(@association.scope)
+        criteria = criteria.any_in(key => keys)
+        criteria.inclusions = criteria.inclusions - [@association]
+        criteria
+      end
diff --git a/lib/mongoid/association/eager_loadable.rb b/lib/mongoid/association/eager_loadable.rb
--- a/lib/mongoid/association/eager_loadable.rb
+++ b/lib/mongoid/association/eager_loadable.rb
@@ -30,6 +30,13 @@ def eager_load(docs)
+      # Load the associations for the given documents using $lookup.
+      #
+      # @return [ Array<Mongoid::Document> ] The given documents.
+      def eager_load_with_lookup
+        preload_for_lookup(criteria)
+      end
+
@@ -66,6 +73,97 @@ def preload(associations, docs)
+
+      # Load the associations for the given documents. This will be done
+      # recursively to load the associations of the given documents'
+      # associated documents.
+      #
+      # @param [ Array<Mongoid::Association::Relatable> ] associations
+      #   The associations to load.
+      # @param [ Array<Mongoid::Document> ] docs The documents.
+      def preload_for_lookup(criteria)
+        assoc_map = criteria.inclusions.group_by(&:inverse_class_name)
+
+        # match first
+        pipeline = criteria.selector.to_pipeline
+        # then sort, skip, limit
+        pipeline.concat(criteria.options.to_pipeline_for_lookup)
+
+        # account for single-collection inheritance
+        root_class = klass.root_class
+
+        if assoc_map[klass.to_s]
+          assoc_map[klass.to_s].each do |assoc|
+            # Create a copy of the mapping for each top-level association to avoid mutation issues
+            pipeline << create_pipeline(assoc, assoc_map.dup)
+          end
+        end
+
+        if klass != root_class && assoc_map[root_class.to_s]
+          assoc_map[root_class.to_s].each do |assoc|
+            # Create a copy of the mapping for each top-level association to avoid mutation issues
+            pipeline << create_pipeline(assoc, assoc_map.dup)
+          end
+        end
+
+        Eager.new(criteria.inclusions, [], true, pipeline).run
+      end
+
+      def switch_local_and_foreign_fields?(association)
+        association.is_a?(Mongoid::Association::Referenced::BelongsTo) ||
+          association.is_a?(Mongoid::Association::Referenced::HasAndBelongsToMany)
+      end
+
+      def create_pipeline(current_assoc, mapping)
+        # Build nested pipeline for children and ordering
+        pipeline_stages = []
+
+        # For belongs_to and has_and_belongs_to_many, the foreign key is on the current document
+        # For has_many/has_one, the foreign key is on the related document
+        if switch_local_and_foreign_fields?(current_assoc)
+          local_field = current_assoc.foreign_key
+          foreign_field = current_assoc.primary_key
+        else
+          local_field = current_assoc.primary_key
+          foreign_field = current_assoc.foreign_key
+        end
+        
+        # Build the 'as' field with embedded path prefix if needed
+        as_field = current_assoc.name.to_s
+        
+        stage = {
+          "$lookup" => {
+            "from" => current_assoc.klass.collection.name,
+            "localField" => local_field,
+            "foreignField" => foreign_field,
+            "as" => as_field
+          }
+        }
+        
+        # Add ordering if defined on the association, or default to _id for consistent order
+        if current_assoc.order
+          sort_spec = current_assoc.order.is_a?(Hash) ? current_assoc.order : { current_assoc.order => 1 }
+          pipeline_stages << { "$sort" => sort_spec }
+        else
+          # Default to sorting by _id to maintain insertion order consistency
+          pipeline_stages << { "$sort" => { "_id" => 1 } }
+        end
+        
+        # Add nested lookups for child associations
+        # Child associations don't need the embedded_path prefix since they're referenced from the looked-up document
+        # Remove this class from the mapping to prevent infinite loops with circular references
+        class_name = current_assoc.klass.to_s
+        if child_assocs = mapping.delete(class_name)
+          child_assocs.each do |child|
+            pipeline_stages << create_pipeline(child, mapping)
+          end
+        end
+        
+        # Always add pipeline since we always have at least $sort
+        stage["$lookup"]["pipeline"] = pipeline_stages
+        
+        stage
+      end
diff --git a/lib/mongoid/association/embedded/embedded_in/proxy.rb b/lib/mongoid/association/embedded/embedded_in/proxy.rb
--- a/lib/mongoid/association/embedded/embedded_in/proxy.rb
+++ b/lib/mongoid/association/embedded/embedded_in/proxy.rb
@@ -90,6 +90,8 @@ class << self
+            # @param [ true | false ] use_lookup Whether to use a $lookup
+            #   aggregation stage to perform the eager load.
diff --git a/lib/mongoid/association/referenced/belongs_to/buildable.rb b/lib/mongoid/association/referenced/belongs_to/buildable.rb
--- a/lib/mongoid/association/referenced/belongs_to/buildable.rb
+++ b/lib/mongoid/association/referenced/belongs_to/buildable.rb
@@ -23,6 +23,22 @@ module Buildable
+            
+            # Handle array from $lookup aggregation (returns array even for belongs_to)
+            if object.is_a?(Array)
+              first = object.first
+              case first
+              when nil, Mongoid::Document then return first
+              when Hash then return Factory.execute_from_db(klass, first, nil, selected_fields, execute_callbacks: false)
+              else raise ArgumentError, "Cannot build belongs_to association from array"
+              end
+            end
+            
+            # Handle single hash from $lookup with $unwind
+            if object.is_a?(Hash)
+              return Factory.execute_from_db(klass, object, nil, selected_fields, execute_callbacks: false)
+            end
+
diff --git a/lib/mongoid/association/referenced/has_and_belongs_to_many/buildable.rb b/lib/mongoid/association/referenced/has_and_belongs_to_many/buildable.rb
--- a/lib/mongoid/association/referenced/has_and_belongs_to_many/buildable.rb
+++ b/lib/mongoid/association/referenced/has_and_belongs_to_many/buildable.rb
@@ -23,6 +23,11 @@ module Buildable
+              # Handle array of hashes from $lookup aggregation
+              if object.is_a?(Array) && object.all? { |o| o.is_a?(Hash) }
+                return object.map { |attrs| Factory.execute_from_db(klass, attrs, nil, selected_fields, execute_callbacks: false) }
+              end
+              
diff --git a/lib/mongoid/association/referenced/has_many/buildable.rb b/lib/mongoid/association/referenced/has_many/buildable.rb
--- a/lib/mongoid/association/referenced/has_many/buildable.rb
+++ b/lib/mongoid/association/referenced/has_many/buildable.rb
@@ -23,6 +23,12 @@ module Buildable
+            
+            # Handle array of hashes from $lookup aggregation
+            if object.is_a?(Array) && object.all? { |o| o.is_a?(Hash) }
+              return object.map { |attrs| Factory.execute_from_db(klass, attrs, nil, selected_fields, execute_callbacks: false) }
+            end
+            
diff --git a/lib/mongoid/association/referenced/has_one/buildable.rb b/lib/mongoid/association/referenced/has_one/buildable.rb
--- a/lib/mongoid/association/referenced/has_one/buildable.rb
+++ b/lib/mongoid/association/referenced/has_one/buildable.rb
@@ -24,6 +24,12 @@ module Buildable
+              # Handle array of hashes from $lookup aggregation
+              if object.is_a?(Array) && object.all? { |o| o.is_a?(Hash) }
+                doc = object.first
+                return doc ? Factory.execute_from_db(klass, doc, nil, selected_fields, execute_callbacks: false) : nil
+              end
+              
diff --git a/lib/mongoid/association/relatable.rb b/lib/mongoid/association/relatable.rb
--- a/lib/mongoid/association/relatable.rb
+++ b/lib/mongoid/association/relatable.rb
@@ -37,6 +37,11 @@ module Relatable
+      # The class that owns this association.
+      #
+      # @return [ Class ] The owner class.
+      attr_reader :owner_class
+
diff --git a/lib/mongoid/contextual/memory.rb b/lib/mongoid/contextual/memory.rb
--- a/lib/mongoid/contextual/memory.rb
+++ b/lib/mongoid/contextual/memory.rb
@@ -141,11 +141,16 @@ def exists?(id_or_conditions = :none)
-        if limit
-          eager_load(documents.first(limit))
+        use_first = limit.nil?
+        limit ||= 1
+        if criteria.use_lookup?
+          @criteria = criteria.limit(limit)
+          result = eager_load_with_lookup()
-          eager_load([documents.first]).first
+          result = eager_load(documents.first(limit))
+
+        use_first ? result.first : result
@@ -530,7 +535,7 @@ def third_to_last!
-          eager_load(docs)
+          criteria.use_lookup? ? ea
... [excerpt truncated]
```

### Human Review Questions

- Does the output match single-line commit subject format?
- Is it faithful to the diff and original message?
- Does it omit any major change?
- Does it hallucinate any unsupported behavior, motive, or effect?
- Does it keep this complex but single-purpose change compressed into one purpose?
- Does it over-segment supporting edits into fake multiple goals?

## Record 3

- Sample ID: `synthetic_multi:badb1a0475c1b9b1`
- Category: `synthetic_multi`
- Strategy: `G4`
- Repo: `dinerojs/dinero.js`
- Repo canonical: `dinerojs/dinero.js`
- Repo parse status: `github_slug`
- SHA: `2b5a8ddc4845d31052de779035030032c6a75b9b`
- Generated subject: `fix: [~] row comparer & add list aprox comparer (#415)`
- Reference subject: `fix: correct doc paths and test greaterThanOrEqual`

### Original Commit Message

```text
fix: correct doc paths and test greaterThanOrEqual
```

### Prompt Metadata

- Prompt chars: `8329`
- Estimated prompt tokens: `2082`
- Status: `generated`
- Thinking mode: `disabled`
- Latency ms: `0`
- Usage: `{'prompt_chars': 8329, 'completion_chars': 54}`

### Automatic Format Checks

- Non-empty: `True`
- Single line: `True`
- Subject length chars: `54`
- Subject length tokens: `8`
- Artifact markers present: `False`

### Diff Excerpt

- Excerpted: `False`
```diff
diff --git a/packages/dinero.js/src/api/__tests__/greaterThanOrEqual.test.ts b/packages/dinero.js/src/api/__tests__/greaterThanOrEqual.test.ts
index 29d9558a..3d9a70e0 100644
--- a/packages/dinero.js/src/api/__tests__/greaterThanOrEqual.test.ts
+++ b/packages/dinero.js/src/api/__tests__/greaterThanOrEqual.test.ts
@@ -1,23 +1,74 @@
-import { USD } from '@dinero.js/currencies';
-import { dinero, greaterThanOrEqual } from '../../..';
+import { USD, EUR } from '@dinero.js/currencies';
+import { dinero, greaterThanOrEqual, unsafeGreaterThanOrEqual } from '../../..';
 
 describe('greaterThanOrEqual', () => {
-  it('returns false when the first amount is less than the other', () => {
-    const d1 = dinero({ amount: 500, currency: USD });
-    const d2 = dinero({ amount: 800, currency: USD });
+  describe('safe', () => {
+    it('returns false when the first amount is less than the other', () => {
+      const d1 = dinero({ amount: 500, currency: USD });
+      const d2 = dinero({ amount: 800, currency: USD });
 
-    expect(greaterThanOrEqual(d1, d2)).toBe(false);
-  });
-  it('returns true when amounts are equal', () => {
-    const d1 = dinero({ amount: 500, currency: USD });
-    const d2 = dinero({ amount: 500, currency: USD });
+      expect(greaterThanOrEqual(d1, d2)).toBe(false);
+    });
+    it('returns true when amounts are equal', () => {
+      const d1 = dinero({ amount: 500, currency: USD });
+      const d2 = dinero({ amount: 500, currency: USD });
+
+      expect(greaterThanOrEqual(d1, d2)).toBe(true);
+    });
+    it('returns true when the first amount is greater than the other', () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 500, currency: USD });
+
+      expect(greaterThanOrEqual(d1, d2)).toBe(true);
+    });
+    it('normalizes the result to the highest scale', () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 5000, currency: USD, scale: 3 });
+
+      expect(greaterThanOrEqual(d1, d2)).toBe(true);
+    });
+    it('throws when using different currencies', () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 500, currency: EUR });
 
-    expect(greaterThanOrEqual(d1, d2)).toBe(true);
+      expect(() => {
+        greaterThanOrEqual(d1, d2);
+      }).toThrowErrorMatchingInlineSnapshot(
+        `"Dinero objects don't have the same currency."`
+      );
+    });
   });
-  it('returns true when the first amount is greater than the other', () => {
-    const d1 = dinero({ amount: 800, currency: USD });
-    const d2 = dinero({ amount: 500, currency: USD });
+  describe('unsafe', () => {
+    it('returns false when the first amount is less than the other', () => {
+      const d1 = dinero({ amount: 500, currency: USD });
+      const d2 = dinero({ amount: 800, currency: USD });
+
+      expect(unsafeGreaterThanOrEqual(d1, d2)).toBe(false);
+    });
+    it('returns true when amounts are equal', () => {
+      const d1 = dinero({ amount: 500, currency: USD });
+      const d2 = dinero({ amount: 500, currency: USD });
+
+      expect(unsafeGreaterThanOrEqual(d1, d2)).toBe(true);
+    });
+    it('returns true when the first amount is greater than the other', () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 500, currency: USD });
+
+      expect(unsafeGreaterThanOrEqual(d1, d2)).toBe(true);
+    });
+    it("doesn't normalize the result to the highest scale, resulting in an incorrect comparison", () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 5000, currency: USD, scale: 3 });
+
+      expect(unsafeGreaterThanOrEqual(d1, d2)).toBe(false);
+    });
+    it("doesn't throw when using different currencies, resulting in an incorrect comparison", () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 500, currency: EUR });
 
-    expect(greaterThanOrEqual(d1, d2)).toBe(true);
+      expect(() => unsafeGreaterThanOrEqual(d1, d2)).not.toThrow();
+      expect(unsafeGreaterThanOrEqual(d1, d2)).toBe(true);
+    });
   });
 });
diff --git a/website/pages/docs/[[...slug]].tsx b/website/pages/docs/[[...slug]].tsx
index 909aa63e..d83ec27c 100644
--- a/website/pages/docs/[[...slug]].tsx
+++ b/website/pages/docs/[[...slug]].tsx
@@ -50,17 +50,15 @@ export const getStaticProps: GetStaticProps = async ({ params }) => {
 
 export const getStaticPaths: GetStaticPaths = async () => {
   const pages = await getFiles('docs');
-  const slugs = pages.map((page) =>
-    page.replace('.mdx', '').split('/').filter(Boolean)
-  );
+  const paths = pages.map((page) => {
+    const slug = page.replace('.mdx', '').split('/').filter(Boolean);
+    const [root] = slug;
 
-  return {
-    paths: slugs
-      .map((slug) => {
-        const [root] = slug;
+    return { params: { slug: root === 'index' ? [] : slug } }
+  });
 
-        return { params: { slug: root === 'index' ? [] : slug } }
-      }),
-    fallback: true,
+  return {
+    paths,
+    fallback: false,
   };
 };
```

### Retrieval Exemplars

- Retrieved exemplar IDs: `['ex:c933ca035f67b397', 'ex:4c1cf10f12621101', 'ex:bf55c32e98b37edd']`
- Similarity scores: `[0.2043623107565659, 0.08287333755344566, 0.07646137634568019]`
- Retrieval quality status: `usable_with_diagnostics`
- Low similarity warning: `True`
- Repo guard exclusion count: `0`
- Leakage checks: `{'same_repo': False, 'same_repo_original_string': False, 'same_repo_canonical': False, 'source_sha_overlap': False, 'diff_fingerprint_overlap': False, 'normalized_subject_overlap': False}`

- Exemplar `ex:c933ca035f67b397`
  - Repo/SHA: `holdenk/spark-testing-base` / `d5bfe78e88d2ad8c8c26702c4e793e563263ad8d`
  - Repo canonical: `holdenk/spark-testing-base`
  - Subject: `fix: [~] row comparer & add list aprox comparer (#415)`
  - Similarity score: `0.2043623107565659`
  - Diff summary: `diff --git a/core/src/main/2.0/scala/com/holdenkarau/spark/testing/DataFrameSuiteBase.scala b/core/src/main/2.0/scala/com/holdenkarau/spark/testing/DataFrameSuiteBase.scala
index f13d92ef..4bca233b 100644
--- a/core/src/main/2.0/scala/com/holdenkarau/spark/testing/DataFrameSuiteBase.scala
+++ b/core/src/main/2.0/scala/com/holdenkarau/spark/testing/DataFrameSuiteBase.scala
@@ -436,6 +436,45 @@ object DataFrameSuiteBase {
   def approxEquals(r1: Row, r2: Row, tolTimestamp: Duration): Boolean =
     approxEquals(r1, r2, 0, tolTimestamp)
 
+  private def compareTimestamp(t1: Timestamp, t2: Timestamp,
+                               tolTimestamp: Duration): Boolean = {
+    !(Duration.between(t1.toInstant, t2.toInstant).abs.compareTo(tolTimestamp) > 0)
+  }`
- Exemplar `ex:4c1cf10f12621101`
  - Repo/SHA: `ccxt/ccxt` / `7c9929931a92bfa9cf565ce2e03391a18631de93`
  - Repo canonical: `ccxt/ccxt`
  - Subject: `refactor: bigone add parsecurrency (#28642)`
  - Similarity score: `0.08287333755344566`
  - Diff summary: `diff --git a/ts/src/bigone.ts b/ts/src/bigone.ts
index 3877038fbb0de..c073d61299819 100644
--- a/ts/src/bigone.ts
+++ b/ts/src/bigone.ts
@@ -523,85 +523,84 @@ export default class bigone extends Exchange {
         // }
         //
         const currenciesData = this.safeList (data, 'data', []);
-        const result: Dict = {};
-        for (let i = 0; i < currenciesData.length; i++) {
-            const currency = currenciesData[i];
-            const id = this.safeString (currency, 'symbol');`
- Exemplar `ex:bf55c32e98b37edd`
  - Repo/SHA: `stacks-network/stacks-core` / `378fc1b80e161ce1b82cc98b3802565222100816`
  - Repo canonical: `stacks-network/stacks-core`
  - Subject: `fix: update changelog for 2.05.0.4.0 and add stx-balance test`
  - Similarity score: `0.07646137634568019`
  - Diff summary: `diff --git a/src/vm/tests/assets.rs b/src/vm/tests/assets.rs
index 617f5b23af..85c716515d 100644
--- a/src/vm/tests/assets.rs
+++ b/src/vm/tests/assets.rs
@@ -106,6 +106,7 @@ fn execute_transaction(env: &mut OwnedEnvironment, issuer: Value, contract_ident
 fn test_native_stx_ops(owned_env: &mut OwnedEnvironment) {
     let contract = "(define-public (burn-stx (amount uint) (p principal)) (stx-burn? amount p))
                     (define-public (xfer-stx (amount uint) (p principal) (t principal)) (stx-transfer? amount p t))
+                    (define-public (balance-stx (p principal)) (stx-balance? p))
                     (define-public (to-contract (amount uint) (p principal))
                       (let ((contract-principal (as-contract tx-sender)))
                         (stx-transfer? amount p contract-principal)))`

### Human Review Questions

- Does the output match single-line commit subject format?
- Is it faithful to the diff and original message?
- Does it omit any major change?
- Does it hallucinate any unsupported behavior, motive, or effect?
- Does it cover both independent intents?
- Does it omit the secondary but still independent intent?
- Do the retrieved examples appear relevant, or does the output mechanically copy them?

## Record 4

- Sample ID: `synthetic_multi:badb1a0475c1b9b1`
- Category: `synthetic_multi`
- Strategy: `G5`
- Repo: `dinerojs/dinero.js`
- Repo canonical: `dinerojs/dinero.js`
- Repo parse status: `github_slug`
- SHA: `2b5a8ddc4845d31052de779035030032c6a75b9b`
- Generated subject: `fix: [~] row comparer & add list aprox comparer (#415)`
- Reference subject: `fix: correct doc paths and test greaterThanOrEqual`

### Original Commit Message

```text
fix: correct doc paths and test greaterThanOrEqual
```

### Prompt Metadata

- Prompt chars: `8727`
- Estimated prompt tokens: `2181`
- Status: `generated`
- Thinking mode: `disabled`
- Latency ms: `0`
- Usage: `{'prompt_chars': 8727, 'completion_chars': 54}`

### Automatic Format Checks

- Non-empty: `True`
- Single line: `True`
- Subject length chars: `54`
- Subject length tokens: `8`
- Artifact markers present: `False`

### Diff Excerpt

- Excerpted: `False`
```diff
diff --git a/packages/dinero.js/src/api/__tests__/greaterThanOrEqual.test.ts b/packages/dinero.js/src/api/__tests__/greaterThanOrEqual.test.ts
index 29d9558a..3d9a70e0 100644
--- a/packages/dinero.js/src/api/__tests__/greaterThanOrEqual.test.ts
+++ b/packages/dinero.js/src/api/__tests__/greaterThanOrEqual.test.ts
@@ -1,23 +1,74 @@
-import { USD } from '@dinero.js/currencies';
-import { dinero, greaterThanOrEqual } from '../../..';
+import { USD, EUR } from '@dinero.js/currencies';
+import { dinero, greaterThanOrEqual, unsafeGreaterThanOrEqual } from '../../..';
 
 describe('greaterThanOrEqual', () => {
-  it('returns false when the first amount is less than the other', () => {
-    const d1 = dinero({ amount: 500, currency: USD });
-    const d2 = dinero({ amount: 800, currency: USD });
+  describe('safe', () => {
+    it('returns false when the first amount is less than the other', () => {
+      const d1 = dinero({ amount: 500, currency: USD });
+      const d2 = dinero({ amount: 800, currency: USD });
 
-    expect(greaterThanOrEqual(d1, d2)).toBe(false);
-  });
-  it('returns true when amounts are equal', () => {
-    const d1 = dinero({ amount: 500, currency: USD });
-    const d2 = dinero({ amount: 500, currency: USD });
+      expect(greaterThanOrEqual(d1, d2)).toBe(false);
+    });
+    it('returns true when amounts are equal', () => {
+      const d1 = dinero({ amount: 500, currency: USD });
+      const d2 = dinero({ amount: 500, currency: USD });
+
+      expect(greaterThanOrEqual(d1, d2)).toBe(true);
+    });
+    it('returns true when the first amount is greater than the other', () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 500, currency: USD });
+
+      expect(greaterThanOrEqual(d1, d2)).toBe(true);
+    });
+    it('normalizes the result to the highest scale', () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 5000, currency: USD, scale: 3 });
+
+      expect(greaterThanOrEqual(d1, d2)).toBe(true);
+    });
+    it('throws when using different currencies', () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 500, currency: EUR });
 
-    expect(greaterThanOrEqual(d1, d2)).toBe(true);
+      expect(() => {
+        greaterThanOrEqual(d1, d2);
+      }).toThrowErrorMatchingInlineSnapshot(
+        `"Dinero objects don't have the same currency."`
+      );
+    });
   });
-  it('returns true when the first amount is greater than the other', () => {
-    const d1 = dinero({ amount: 800, currency: USD });
-    const d2 = dinero({ amount: 500, currency: USD });
+  describe('unsafe', () => {
+    it('returns false when the first amount is less than the other', () => {
+      const d1 = dinero({ amount: 500, currency: USD });
+      const d2 = dinero({ amount: 800, currency: USD });
+
+      expect(unsafeGreaterThanOrEqual(d1, d2)).toBe(false);
+    });
+    it('returns true when amounts are equal', () => {
+      const d1 = dinero({ amount: 500, currency: USD });
+      const d2 = dinero({ amount: 500, currency: USD });
+
+      expect(unsafeGreaterThanOrEqual(d1, d2)).toBe(true);
+    });
+    it('returns true when the first amount is greater than the other', () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 500, currency: USD });
+
+      expect(unsafeGreaterThanOrEqual(d1, d2)).toBe(true);
+    });
+    it("doesn't normalize the result to the highest scale, resulting in an incorrect comparison", () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 5000, currency: USD, scale: 3 });
+
+      expect(unsafeGreaterThanOrEqual(d1, d2)).toBe(false);
+    });
+    it("doesn't throw when using different currencies, resulting in an incorrect comparison", () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 500, currency: EUR });
 
-    expect(greaterThanOrEqual(d1, d2)).toBe(true);
+      expect(() => unsafeGreaterThanOrEqual(d1, d2)).not.toThrow();
+      expect(unsafeGreaterThanOrEqual(d1, d2)).toBe(true);
+    });
   });
 });
diff --git a/website/pages/docs/[[...slug]].tsx b/website/pages/docs/[[...slug]].tsx
index 909aa63e..d83ec27c 100644
--- a/website/pages/docs/[[...slug]].tsx
+++ b/website/pages/docs/[[...slug]].tsx
@@ -50,17 +50,15 @@ export const getStaticProps: GetStaticProps = async ({ params }) => {
 
 export const getStaticPaths: GetStaticPaths = async () => {
   const pages = await getFiles('docs');
-  const slugs = pages.map((page) =>
-    page.replace('.mdx', '').split('/').filter(Boolean)
-  );
+  const paths = pages.map((page) => {
+    const slug = page.replace('.mdx', '').split('/').filter(Boolean);
+    const [root] = slug;
 
-  return {
-    paths: slugs
-      .map((slug) => {
-        const [root] = slug;
+    return { params: { slug: root === 'index' ? [] : slug } }
+  });
 
-        return { params: { slug: root === 'index' ? [] : slug } }
-      }),
-    fallback: true,
+  return {
+    paths,
+    fallback: false,
   };
 };
```

### Retrieval Exemplars

- Retrieved exemplar IDs: `['ex:c933ca035f67b397', 'ex:4c1cf10f12621101', 'ex:bf55c32e98b37edd']`
- Similarity scores: `[0.2043623107565659, 0.08287333755344566, 0.07646137634568019]`
- Retrieval quality status: `usable_with_diagnostics`
- Low similarity warning: `True`
- Repo guard exclusion count: `0`
- Leakage checks: `{'same_repo': False, 'same_repo_original_string': False, 'same_repo_canonical': False, 'source_sha_overlap': False, 'diff_fingerprint_overlap': False, 'normalized_subject_overlap': False}`

- Exemplar `ex:c933ca035f67b397`
  - Repo/SHA: `holdenk/spark-testing-base` / `d5bfe78e88d2ad8c8c26702c4e793e563263ad8d`
  - Repo canonical: `holdenk/spark-testing-base`
  - Subject: `fix: [~] row comparer & add list aprox comparer (#415)`
  - Similarity score: `0.2043623107565659`
  - Diff summary: `diff --git a/core/src/main/2.0/scala/com/holdenkarau/spark/testing/DataFrameSuiteBase.scala b/core/src/main/2.0/scala/com/holdenkarau/spark/testing/DataFrameSuiteBase.scala
index f13d92ef..4bca233b 100644
--- a/core/src/main/2.0/scala/com/holdenkarau/spark/testing/DataFrameSuiteBase.scala
+++ b/core/src/main/2.0/scala/com/holdenkarau/spark/testing/DataFrameSuiteBase.scala
@@ -436,6 +436,45 @@ object DataFrameSuiteBase {
   def approxEquals(r1: Row, r2: Row, tolTimestamp: Duration): Boolean =
     approxEquals(r1, r2, 0, tolTimestamp)
 
+  private def compareTimestamp(t1: Timestamp, t2: Timestamp,
+                               tolTimestamp: Duration): Boolean = {
+    !(Duration.between(t1.toInstant, t2.toInstant).abs.compareTo(tolTimestamp) > 0)
+  }`
- Exemplar `ex:4c1cf10f12621101`
  - Repo/SHA: `ccxt/ccxt` / `7c9929931a92bfa9cf565ce2e03391a18631de93`
  - Repo canonical: `ccxt/ccxt`
  - Subject: `refactor: bigone add parsecurrency (#28642)`
  - Similarity score: `0.08287333755344566`
  - Diff summary: `diff --git a/ts/src/bigone.ts b/ts/src/bigone.ts
index 3877038fbb0de..c073d61299819 100644
--- a/ts/src/bigone.ts
+++ b/ts/src/bigone.ts
@@ -523,85 +523,84 @@ export default class bigone extends Exchange {
         // }
         //
         const currenciesData = this.safeList (data, 'data', []);
-        const result: Dict = {};
-        for (let i = 0; i < currenciesData.length; i++) {
-            const currency = currenciesData[i];
-            const id = this.safeString (currency, 'symbol');`
- Exemplar `ex:bf55c32e98b37edd`
  - Repo/SHA: `stacks-network/stacks-core` / `378fc1b80e161ce1b82cc98b3802565222100816`
  - Repo canonical: `stacks-network/stacks-core`
  - Subject: `fix: update changelog for 2.05.0.4.0 and add stx-balance test`
  - Similarity score: `0.07646137634568019`
  - Diff summary: `diff --git a/src/vm/tests/assets.rs b/src/vm/tests/assets.rs
index 617f5b23af..85c716515d 100644
--- a/src/vm/tests/assets.rs
+++ b/src/vm/tests/assets.rs
@@ -106,6 +106,7 @@ fn execute_transaction(env: &mut OwnedEnvironment, issuer: Value, contract_ident
 fn test_native_stx_ops(owned_env: &mut OwnedEnvironment) {
     let contract = "(define-public (burn-stx (amount uint) (p principal)) (stx-burn? amount p))
                     (define-public (xfer-stx (amount uint) (p principal) (t principal)) (stx-transfer? amount p t))
+                    (define-public (balance-stx (p principal)) (stx-balance? p))
                     (define-public (to-contract (amount uint) (p principal))
                       (let ((contract-principal (as-contract tx-sender)))
                         (stx-transfer? amount p contract-principal)))`

### Oracle Intent Plan

- Oracle intent count: `2`
- Oracle intent subjects: `['fix: fix how paths are passed', 'test: add missing tests for greaterThanOrEqual function']`
- Oracle edit-to-intent: `{'h0': 1, 'h1': 0}`
- Supporting edit note: `Use the structure as evidence. Do not copy the plan mechanically.`

### Human Review Questions

- Does the output match single-line commit subject format?
- Is it faithful to the diff and original message?
- Does it omit any major change?
- Does it hallucinate any unsupported behavior, motive, or effect?
- Is it more complete than the G4 output for the same sample?
- Is it more faithful than the G4 output for the same sample?
- Does it mechanically copy the oracle plan?
- Does the oracle plan skew the emphasis away from the actual diff?

## Record 5

- Sample ID: `M_real_multi:7da239a00c1c6f17`
- Category: `M_real_multi`
- Strategy: `G4`
- Repo: `ArthurSonzogni/FTXUI`
- Repo canonical: `arthursonzogni/ftxui`
- Repo parse status: `github_slug`
- SHA: `98c650d2ba6c22cb00bf3a3b3a7d1acd3d92ca1e`
- Generated subject: `Add C17 and C23 output`
- Reference subject: `Improve ABI stability for 7.0.0 and optimize rendering performance (#1271)`

### Original Commit Message

```text
Improve ABI stability for 7.0.0 and optimize rendering performance (#1271)

* Improve ABI stability for 7.0.0

- Implement PIMPL for ComponentBase.
- Export internal symbols required for shared library build and tests.

* Optimize Surface::Clear

* Update ABI fingerprint

* Stop exporting symbols from src/ftxui

* Fix Surface::Clear implementation

* Build system: add version and test status to summary

* CMake: add safety error when building tests with shared libraries
```

### Prompt Metadata

- Prompt chars: `27833`
- Estimated prompt tokens: `6958`
- Status: `generated`
- Thinking mode: `disabled`
- Latency ms: `0`
- Usage: `{'prompt_chars': 27833, 'completion_chars': 22}`

### Automatic Format Checks

- Non-empty: `True`
- Single line: `True`
- Subject length chars: `22`
- Subject length tokens: `5`
- Artifact markers present: `False`

### Diff Excerpt

- Excerpted: `True`
```diff
diff --git a/cmake/ftxui_message.cmake b/cmake/ftxui_message.cmake
--- a/cmake/ftxui_message.cmake
+++ b/cmake/ftxui_message.cmake
@@ -4,7 +4,7 @@ function(ftxui_message msg)
-ftxui_message("┌─ FTXUI options ─────────────────────")
+ftxui_message("┌─ FTXUI ${PROJECT_VERSION} ────────────────────────")
diff --git a/cmake/ftxui_test.cmake b/cmake/ftxui_test.cmake
--- a/cmake/ftxui_test.cmake
+++ b/cmake/ftxui_test.cmake
@@ -2,6 +2,10 @@ if (NOT FTXUI_BUILD_TESTS)
+if (BUILD_SHARED_LIBS)
+  message(FATAL_ERROR "FTXUI unit tests require access to internal symbols which are hidden when building as shared libraries. To run tests, please configure with -DBUILD_SHARED_LIBS=OFF.")
+endif()
+
diff --git a/include/ftxui/component/component_base.hpp b/include/ftxui/component/component_base.hpp
--- a/include/ftxui/component/component_base.hpp
+++ b/include/ftxui/component/component_base.hpp
@@ -30,10 +30,9 @@ using Components = std::vector<Component>;
-  explicit ComponentBase(Components children)
-      : children_(std::move(children)) {}
+  explicit ComponentBase(Components children);
-  ComponentBase() = default;
+  ComponentBase();
@@ -94,11 +93,12 @@ class FTXUI_EXPORT(COMPONENT) ComponentBase {
-  Components children_;
+  Components& children();
+  const Components& children() const;
-  ComponentBase* parent_ = nullptr;
-  bool in_render = false;
+  struct Impl;
+  std::unique_ptr<Impl> impl_;
diff --git a/include/ftxui/dom/node.hpp b/include/ftxui/dom/node.hpp
--- a/include/ftxui/dom/node.hpp
+++ b/include/ftxui/dom/node.hpp
@@ -74,6 +74,16 @@ class FTXUI_EXPORT(DOM) Node {
+  // ABI Reserve:
+  virtual void Reserved1();
+  virtual void Reserved2();
+  virtual void Reserved3();
+  virtual void Reserved4();
+  virtual void Reserved5();
+  virtual void Reserved6();
+  virtual void Reserved7();
+  virtual void Reserved8();
+
diff --git a/include/ftxui/screen/surface.hpp b/include/ftxui/screen/surface.hpp
--- a/include/ftxui/screen/surface.hpp
+++ b/include/ftxui/screen/surface.hpp
@@ -49,9 +49,12 @@ class FTXUI_EXPORT(SCREEN) Surface {
+  Cell& FastCellAt(int x, int y);
+  const Cell& FastCellAt(int x, int y) const;
+
-  std::vector<std::vector<Cell>> cells_;
+  std::vector<Cell> cells_;
diff --git a/include/ftxui/util/export.hpp b/include/ftxui/util/export.hpp
--- a/include/ftxui/util/export.hpp
+++ b/include/ftxui/util/export.hpp
@@ -70,7 +70,7 @@
-  FTXUI_MACRO_EXPAND(FTXUI_MACRO_CONDITIONAL_COMMA_IMPL_(__VA_ARGS__, ))
+  FTXUI_MACRO_EXPAND(FTXUI_MACRO_CONDITIONAL_COMMA_IMPL_(__VA_ARGS__, dummy))
@@ -79,7 +79,8 @@
-  FTXUI_MACRO_EXPAND(FTXUI_MACRO_SELECT_THIRD_ARGUMENT_IMPL_(__VA_ARGS__))
+  FTXUI_MACRO_EXPAND(                               \
+      FTXUI_MACRO_SELECT_THIRD_ARGUMENT_IMPL_(__VA_ARGS__, dummy))
diff --git a/meson.build b/meson.build
--- a/meson.build
+++ b/meson.build
@@ -141,3 +141,9 @@ endif
+
+summary({
+  'Version': meson.project_version(),
+  'Build Tests': ftxui_build_tests,
+  'Build Examples': ftxui_build_examples,
+}, section: 'Project Configuration')
diff --git a/src/ftxui/component/app.cpp b/src/ftxui/component/app.cpp
--- a/src/ftxui/component/app.cpp
+++ b/src/ftxui/component/app.cpp
@@ -916,7 +916,7 @@ void App::Internal::Draw(Component component) {
-        std::vector<std::vector<Cell>>(dimy, std::vector<Cell>(dimx));
+        std::vector<Cell>(static_cast<size_t>(dimx) * static_cast<size_t>(dimy));
diff --git a/src/ftxui/component/component.cpp b/src/ftxui/component/component.cpp
--- a/src/ftxui/component/component.cpp
+++ b/src/ftxui/component/component.cpp
@@ -28,35 +28,56 @@ namespace {
+struct ComponentBase::Impl {
+  Components children;
+  ComponentBase* parent = nullptr;
+  bool in_render = false;
+};
+
+ComponentBase::ComponentBase() : impl_(std::make_unique<Impl>()) {}
+
+ComponentBase::ComponentBase(Components children)
+    : impl_(std::make_unique<Impl>()) {
+  impl_->children = std::move(children);
+}
+
+Components& ComponentBase::children() {
+  return impl_->children;
+}
+
+const Components& ComponentBase::children() const {
+  return impl_->children;
+}
+
-  return parent_;
+  return impl_->parent;
-  return children_[i];
+  return impl_->children[i];
-  return children_.size();
+  return impl_->children.size();
-  if (parent_ == nullptr) {
+  if (impl_->parent == nullptr) {
-  for (const Component& child : parent_->children_) {
+  for (const Component& child : impl_->parent->impl_->children) {
@@ -69,31 +90,31 @@ int ComponentBase::Index() const {
-  child->parent_ = this;
-  children_.push_back(std::move(child));
+  child->impl_->parent = this;
+  impl_->children.push_back(std::move(child));
-  if (parent_ == nullptr) {
+  if (impl_->parent == nullptr) {
-  auto it = std::find_if(std::begin(parent_->children_),  // NOLINT
-                         std::end(parent_->children_),    //
-                         [this](const Component& that) {  //
+  auto it = std::find_if(std::begin(impl_->parent->impl_->children),  // NOLINT
+                         std::end(impl_->parent->impl_->children),    //
+                         [this](const Component& that) {              //
-  ComponentBase* parent = parent_;
-  parent_ = nullptr;
-  parent->children_.erase(it);  // Might delete |this|.
+  ComponentBase* parent = impl_->parent;
+  impl_->parent = nullptr;
+  parent->impl_->children.erase(it);  // Might delete |this|.
-  while (!children_.empty()) {
-    children_[0]->Detach();
+  while (!impl_->children.empty()) {
+    impl_->children[0]->Detach();
@@ -103,13 +124,13 @@ void ComponentBase::DetachAllChildren() {
-  if (in_render) {
+  if (impl_->in_render) {
-  in_render = true;
+  impl_->in_render = true;
-  in_render = false;
+  impl_->in_render = false;
@@ -138,8 +159,8 @@ Element ComponentBase::Render() {
-  if (children_.size() == 1) {
-    return children_.front()->Render();
+  if (impl_->children.size() == 1) {
+    return impl_->children.front()->Render();
@@ -150,8 +171,8 @@ Element ComponentBase::OnRender() {
-bool ComponentBase::OnEvent(Event event) {  // NOLINT
-  for (Component& child : children_) {      // NOLINT
+bool ComponentBase::OnEvent(Event event) {     // NOLINT
+  for (Component& child : impl_->children) {  // NOLINT
@@ -163,7 +184,7 @@ bool ComponentBase::OnEvent(Event event) {  // NOLINT
-  for (const Component& child : children_) {
+  for (const Component& child : impl_->children) {
@@ -171,7 +192,7 @@ void ComponentBase::OnAnimation(animation::Params& params) {
-  for (auto& child : children_) {
+  for (auto& child : impl_->children) {
@@ -183,7 +204,7 @@ Component ComponentBase::ActiveChild() {
-  for (const Component& child : children_) {  // NOLINT
+  for (const Component& child : impl_->children) {  // NOLINT
@@ -193,7 +214,7 @@ bool ComponentBase::Focusable() const {
-  return parent_ == nullptr || parent_->ActiveChild().get() == this;
+  return impl_->parent == nullptr || impl_->parent->ActiveChild().get() == this;
@@ -203,7 +224,7 @@ bool ComponentBase::Active() const {
-    current = current->parent_;
+    current = current->impl_->parent;
@@ -221,7 +242,7 @@ void ComponentBase::SetActiveChild(Component child) {  // NOLINT
-  while (ComponentBase* parent = child->parent_) {
+  while (ComponentBase* parent = child->impl_->parent) {
diff --git a/src/ftxui/component/container.cpp b/src/ftxui/component/container.cpp
--- a/src/ftxui/component/container.cpp
+++ b/src/ftxui/component/container.cpp
@@ -42,16 +42,16 @@ class ContainerBase : public ComponentBase {
-    if (children_.empty()) {
+    if (children().empty()) {
-    return children_[static_cast<size_t>(*selector_) % children_.size()];
+    return children()[static_cast<size_t>(*selector_) % children().size()];
-    for (size_t i = 0; i < children_.size(); ++i) {
-      if (children_[i].get() == child) {
+    for (size_t i = 0; i < children().size(); ++i) {
+      if (children()[i].get() == child) {
@@ -70,9 +70,9 @@ class ContainerBase : public ComponentBase {
-    for (int i = *selector_ + dir; i >= 0 && i < int(children_.size());
+    for (int i = *selector_ + dir; i >= 0 && i < int(children().size());
-      if (children_[i]->Focusable()) {
+      if (children()[i]->Focusable()) {
@@ -80,13 +80,13 @@ class ContainerBase : public ComponentBase {
-    if (children_.empty()) {
+    if (children().empty()) {
-    for (size_t offset = 1; offset < children_.size(); ++offset) {
+    for (size_t offset = 1; offset < children().size(); ++offset) {
-          (*selector_ + offset * dir + children_.size()) % children_.size();
-      if (children_[i]->Focusable()) {
+          (*selector_ + offset * dir + children().size()) % children().size();
+      if (children()[i]->Focusable()) {
@@ -100,8 +100,8 @@ class VerticalContainer : public ContainerBase {
-    elements.reserve(children_.size());
-    for (auto& it : children_) {
+    elements.reserve(children().size());
+    for (auto& it : children()) {
@@ -129,12 +129,12 @@ class VerticalContainer : public ContainerBase {
-      for (size_t i = 0; i < children_.size(); ++i) {
+      for (size_t i = 0; i < children().size(); ++i) {
-      for (size_t i = 0; i < children_.size(); ++i) {
+      for (size_t i = 0; i < children().size(); ++i) {
@@ -145,7 +145,7 @@ class VerticalContainer : public ContainerBase {
-    *selector_ = std::max(0, std::min(int(children_.size()) - 1, *selector_));
+    *selector_ = std::max(0, std::min(int(children().size()) - 1, *selector_));
@@ -170,7 +170,7 @@ class VerticalContainer : public ContainerBase {
-    *selector_ = std::max(0, std::min(int(children_.size()) - 1, *selector_));
+    *selector_ = std::max(0, std::min(int(children().size()) - 1, *selector_));
@@ -184,8 +184,8 @@ class HorizontalContainer : public ContainerBase {
-    elements.reserve(children_.size());
-    for (auto& it : children_) {
+    elements.reserve(children().size());
+    for (auto& it : children()) {
@@ -209,7 +209,7 @@ class HorizontalContainer : public ContainerBase {
-    *selector_ = std::max(0, std::min(int(children_.size()) - 1, *selector_));
+    *selector_ = std::max(0, std::min(int(children().size()) - 1, *selector_));
@@ -227,10 +227,10 @@ class TabContainer : public ContainerBase {
-    if (children_.empty()) {
+    if (children().empty()) {
-    return children_[size_t(*selector_) % children_.size()]->Focusable();
+    return children()[size_t(*selector_) % children().size()]->Focusable();
@@ -246,7 +246,7 @@ class StackedContainer : public ContainerBase {
-    for (auto& child : children_) {
+    for (auto& child : children()) {
@@ -255,7 +255,7 @@ class StackedContainer : public ContainerBase {
-    for (const auto& child : children_) {
+    for (const auto& child : children()) {
@@ -264,30 +264,30 @@ class StackedContainer : public ContainerBase {
-    if (children_.empty()) {
+    if (children().empty()) {
-    return children_[0];
+    return children()[0];
-    if (children_.empty()) {
+    if (children().empty()) {
-        std::find_if(children_.begin(), children_.end(),  // NOLINT
+        std::find_if(children().begin(), children().end(),  // NOLINT
-    if (it == children_.end()) {
+    if (it == children().end()) {
-    std::rotate(children_.begin(), it, it + 1);
+    std::rotate(children().begin(), it, it + 1);
-    for (auto& child : children_) {
+    for (auto& child : children()) {
diff --git a/src/ftxui/dom/node.cpp b/src/ftxui/dom/node.cpp
--- a/src/ftxui/dom/node.cpp
+++ b/src/ftxui/dom/node.cpp
@@ -79,6 +79,15 @@ std::string Node::GetSelectedContent(Selection& selection) {
+void Node::Reserved1() {}
+void Node::Reserved2() {}
+void Node::Reserved3() {}
+void Node::Reserved4() {}
+void Node::Reserved5() {}
+void Node::Reserved6() {}
+void Node::Reserved7() {}
+void Node::Reserved8() {}
+
diff --git a/src/ftxui/screen/screen.cpp b/src/ftxui/screen/screen.cpp
--- a/src/ftxui/screen/screen.cpp
+++ b/src/ftxui/screen/screen.cpp
@@ -450,21 +450,26 @@ void Screen::ToString(std::string& ss) const {
-    for (const auto& cell : cells_[y]) {
-      if
... [excerpt truncated]
```

### Retrieval Exemplars

- Retrieved exemplar IDs: `['ex:f4e65aede2b319fc', 'ex:3c4a54f4125d12f0', 'ex:f7f991b3d96d730a']`
- Similarity scores: `[0.26186589922256576, 0.17224419575083208, 0.16127156557432862]`
- Retrieval quality status: `usable_with_diagnostics`
- Low similarity warning: `False`
- Repo guard exclusion count: `0`
- Leakage checks: `{'same_repo': False, 'same_repo_original_string': False, 'same_repo_canonical': False, 'source_sha_overlap': False, 'diff_fingerprint_overlap': False, 'normalized_subject_overlap': False}`

- Canonical repo exclusions from exemplar pool:
  - ex:c066b8142b1ab31b | arthursonzogni/ftxui -> arthursonzogni/ftxui | ['pilot_repo_canonical']

- Exemplar `ex:f4e65aede2b319fc`
  - Repo/SHA: `friendlyanon/cmake-init` / `ac866f4e6bb957a5b6f9674ad4daa3ba1584a24c`
  - Repo canonical: `friendlyanon/cmake-init`
  - Subject: `Add C17 and C23 output`
  - Similarity score: `0.26186589922256576`
  - Diff summary: `diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
index 74fee519..46e07d76 100644
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -36,7 +36,7 @@ jobs:
       fail-fast: false
 
       matrix:
-        job: [1, 2, 3, 4, 5, 6, 7, 8]
+        job: [1, 2, 3, 4, 5, 6, 7, 8, 9]
 
         pm: [none, conan, vcpkg]`
- Exemplar `ex:3c4a54f4125d12f0`
  - Repo/SHA: `nvidia/dali` / `7558cc49bc31a87fc48fda416dd964725810f9c3`
  - Repo canonical: `nvidia/dali`
  - Subject: `Make nvImageCodec the default decoder and remove legacy (#6306)`
  - Similarity score: `0.17224419575083208`
  - Diff summary: `diff --git a/CMakeLists.txt b/CMakeLists.txt
index e7401e4b308..9e591628928 100644
--- a/CMakeLists.txt
+++ b/CMakeLists.txt
@@ -88,7 +88,7 @@ cmake_dependent_option(USE_PREBUILD_PYBIND11 "Use prebuilt pybind11 from the sys
                        "BUILD_PYTHON" OFF)
 cmake_dependent_option(BUILD_LMDB "Build LMDB readers" ON
                        "NOT BUILD_DALI_NODEPS" OFF)
-cmake_dependent_option(BUILD_JPEG_TURBO "Build with libjpeg-turbo support" ON
+cmake_dependent_option(BUILD_LIBJPEG_TURBO "Build with libjpeg-turbo support" ON
                        "NOT BUILD_DALI_NODEPS" OFF)
 cmake_dependent_option(BUILD_LIBTIFF "Build with libtiff support" ON`
- Exemplar `ex:f7f991b3d96d730a`
  - Repo/SHA: `curl/curl` / `066478f6346a2d987a9ecc3bd3bf45764d69c1c4`
  - Repo canonical: `curl/curl`
  - Subject: `src: add `curlx_memzero()` to clear buffers securely`
  - Similarity score: `0.16127156557432862`
  - Diff summary: `diff --git a/.github/workflows/macos.yml b/.github/workflows/macos.yml
index 3cda27766ada..e0250f562421 100644
--- a/.github/workflows/macos.yml
+++ b/.github/workflows/macos.yml
@@ -36,7 +36,7 @@ permissions: {}
 # or runtime:
 #
 # - 10.7   Lion (2011)          - GSS (build-time, deprecated MIT Kerberos shim)
-# - 10.9   Mavericks (2013)     - LDAP (build-time, deprecated), OCSP (runtime)
+# - 10.9   Mavericks (2013)     - LDAP (build-time, deprecated), memset_s(), OCSP (runtime)
 # - 10.11  El Capitan (2015)    - connectx() (runtime)
 # - 10.12  Sierra (2016)        - clock_gettime() (build-time, runtime)`

### Human Review Questions

- Does the output match single-line commit subject format?
- Is it faithful to the diff and original message?
- Does it omit any major change?
- Does it hallucinate any unsupported behavior, motive, or effect?
- Does it cover the real major goals visible in the diff?
- Does it infer an unsupported rationale, especially phrases like `for ABI stability`?
